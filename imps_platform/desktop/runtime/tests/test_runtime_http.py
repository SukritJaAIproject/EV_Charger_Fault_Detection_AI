from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import imps_fault_runtime  # noqa: E402
from dataset_service import TrainingDatasetService  # noqa: E402


TOKEN = "a" * 64
ORIGIN = "http://127.0.0.1:3999"
SUMMARY = {
    "source": "full_fleet",
    "dataset": {"sessions": 1},
    "leaderboard": [{"id": "agentic-ai", "rank": 1}],
    "analysis": {"byStation": []},
}


class _JobServiceStub:
    @staticmethod
    def health() -> dict:
        return {"ready": True}

    @staticmethod
    def get_job(job_id: str) -> dict:
        return {"jobId": job_id}


class RuntimeHttpTests(unittest.TestCase):
    def start(self, *, datasets: TrainingDatasetService | None, retraining_error: str | None = None) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a: None)
        port = server.server_address[1]
        server.RequestHandlerClass = imps_fault_runtime._make_handler(
            summary=SUMMARY,
            summary_bytes=json.dumps(SUMMARY).encode("utf-8"),
            summary_etag='"x"',
            job_service=_JobServiceStub(),
            dataset_service=datasets,
            training_service=None,
            allowed_origin=ORIGIN,
            port=port,
            api_token=TOKEN,
            retraining_error=retraining_error,
        )
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = port

    def request(self, method: str, path: str, *, token: str | None = TOKEN, body: dict | None = None) -> tuple[int, dict, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        if token is not None:
            headers["X-iMPS-Token"] = token
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(payload))
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        parsed = json.loads(raw) if raw else {}
        return response.status, parsed, dict(response.getheaders())

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.datasets = TrainingDatasetService(Path(self.temp.name) / "datasets")

    def test_every_route_but_health_requires_the_launch_token(self) -> None:
        self.start(datasets=self.datasets)
        self.assertEqual(self.request("GET", "/health", token=None)[0], 200)
        for method, path in (
            ("GET", "/ai/fault-detection/summary"),
            ("GET", "/ai/fault-detection/datasets"),
            ("GET", "/ai/fault-detection/jobs/" + "0" * 32),
            ("POST", "/ai/fault-detection/datasets/imports"),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.request(method, path, token=None)[0], 401)
                self.assertEqual(self.request(method, path, token="b" * 64)[0], 401)
        status, body, _ = self.request("GET", "/ai/fault-detection/datasets")
        self.assertEqual(status, 200)
        self.assertEqual(body["imports"], [])

    def test_preflight_allows_the_token_header(self) -> None:
        self.start(datasets=self.datasets)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("OPTIONS", "/ai/fault-detection/datasets", headers={
            "Host": f"127.0.0.1:{self.port}",
            "Origin": ORIGIN,
            "Access-Control-Request-Headers": "x-imps-token",
        })
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(response.status, 204)
        self.assertIn("X-iMPS-Token", response.getheader("Access-Control-Allow-Headers"))

    def test_unexpected_service_failure_is_a_json_500(self) -> None:
        self.start(datasets=self.datasets)
        with mock.patch.object(self.datasets, "summary", side_effect=PermissionError(13, "locked by scanner")):
            status, body, _ = self.request("GET", "/ai/fault-detection/datasets")
        self.assertEqual(status, 500)
        self.assertIn("detail", body)

    def test_service_errors_keep_their_status(self) -> None:
        self.start(datasets=self.datasets)
        status, body, _ = self.request("GET", f"/ai/fault-detection/datasets/imports/{'0' * 32}/labels")
        self.assertEqual(status, 404)
        self.assertIn("not found", body["detail"])

    def test_unusable_retraining_store_disables_only_those_routes(self) -> None:
        self.start(datasets=None, retraining_error="Dataset storage cannot use links or junctions.")
        status, health, _ = self.request("GET", "/health", token=None)
        self.assertEqual(status, 200)
        self.assertTrue(health["inferenceReady"])
        self.assertFalse(health["retraining"]["available"])
        self.assertIn("junctions", health["retraining"]["reason"])
        for method, path, body in (
            ("GET", "/ai/fault-detection/datasets", None),
            ("GET", "/ai/fault-detection/training", None),
            ("POST", "/ai/fault-detection/training/preview", {"importIds": ["0" * 32]}),
            ("POST", "/ai/fault-detection/datasets/imports", {"name": "x", "sourceType": "folder"}),
        ):
            with self.subTest(path=path):
                status, payload, _ = self.request(method, path, body=body)
                self.assertEqual(status, 503)
                self.assertIn("junctions", payload["detail"])
        self.assertEqual(self.request("GET", "/ai/fault-detection/summary")[0], 200)

    def test_failed_import_can_be_discarded_over_http(self) -> None:
        self.start(datasets=self.datasets)
        status, created, _ = self.request(
            "POST", "/ai/fault-detection/datasets/imports", body={"name": "Empty", "sourceType": "folder"}
        )
        self.assertEqual(status, 201)
        import_id = created["importId"]
        status, _, _ = self.request("POST", f"/ai/fault-detection/datasets/imports/{import_id}/complete")
        self.assertEqual(status, 422)
        status, listed, _ = self.request("GET", "/ai/fault-detection/datasets")
        self.assertEqual(listed["imports"][0]["status"], "failed")
        status, discarded, _ = self.request("POST", f"/ai/fault-detection/datasets/imports/{import_id}/discard")
        self.assertEqual(status, 200)
        self.assertTrue(discarded["discarded"])
        self.assertEqual(self.request("GET", "/ai/fault-detection/datasets")[1]["imports"], [])


if __name__ == "__main__":
    unittest.main()

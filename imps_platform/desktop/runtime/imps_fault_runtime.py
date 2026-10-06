"""Portable loopback API and PCAP inference worker for iMPS desktop."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import signal
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import detection_policy
from dataset_service import DatasetServiceError, TrainingDatasetService
from job_service import JobServiceError, PcapJobService
from training_service import ModelTrainingService, TrainingServiceError


SERVICE_NAME = "fault-detection-portable"
SERVICE_HEADER = "X-iMPS-Desktop-Service"
# Per-launch secret from the Electron launcher. Every route except GET /health
# requires it, so another local process or Windows account that finds the port
# cannot read datasets, rewrite ground truth or start training runs.
TOKEN_HEADER = "X-iMPS-Token"
TOKEN_ENV = "IMPS_API_TOKEN"


def _load_summary(path: Path) -> tuple[dict[str, Any], bytes, str]:
    try:
        raw = path.resolve(strict=True).read_bytes()
        if not raw or len(raw) > 16 * 1024 * 1024:
            raise ValueError("invalid summary size")
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Summary snapshot is missing or invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Summary snapshot must be a JSON object")
    dataset = payload.get("dataset")
    leaderboard = payload.get("leaderboard")
    analysis = payload.get("analysis")
    if (
        payload.get("source") != "full_fleet"
        or not isinstance(dataset, dict)
        or not isinstance(dataset.get("sessions"), int)
        or dataset["sessions"] < 0
        or not isinstance(leaderboard, list)
        or not leaderboard
        or not isinstance(analysis, dict)
        or not isinstance(analysis.get("byStation"), list)
    ):
        raise SystemExit("Summary snapshot failed structural validation")
    etag = '"' + hashlib.sha256(raw).hexdigest() + '"'
    return payload, raw, etag


def _validate_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise SystemExit("--origin must be a loopback HTTP origin with a port")
    return origin.rstrip("/")


def _runtime_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve())]


def _make_handler(
    *,
    summary: dict[str, Any],
    summary_bytes: bytes,
    summary_etag: str,
    job_service: PcapJobService,
    dataset_service: TrainingDatasetService | None,
    training_service: ModelTrainingService | None,
    allowed_origin: str,
    port: int,
    product_name: str | None = None,
    app_version: str | None = None,
    api_token: str | None = None,
    retraining_error: str | None = None,
):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    retraining_reason = retraining_error or "Dataset and training storage is unavailable."

    class RetrainingUnavailable(Exception):
        pass

    def datasets() -> TrainingDatasetService:
        if dataset_service is None:
            raise RetrainingUnavailable(retraining_reason)
        return dataset_service

    def training() -> ModelTrainingService:
        if training_service is None:
            raise RetrainingUnavailable(retraining_reason)
        return training_service

    class Handler(BaseHTTPRequestHandler):
        server_version = "iMPSFaultRuntime/1.0"
        _responded = False

        def _is_allowed(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            origin = self.headers.get("Origin")
            return host in allowed_hosts and (origin is None or origin == allowed_origin)

        def _has_token(self) -> bool:
            if not api_token:
                return True
            supplied = self.headers.get(TOKEN_HEADER) or ""
            return hmac.compare_digest(supplied.encode("utf-8", "replace"), api_token.encode("utf-8"))

        def _guarded(self, route: Any, *args: Any) -> None:
            """Every route answers with JSON, whatever fails underneath."""
            self._responded = False
            try:
                route(*args)
            except RetrainingUnavailable as exc:
                if not self._responded:
                    self._error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
            except (DatasetServiceError, TrainingServiceError, JobServiceError) as exc:
                if not self._responded:
                    self._error(HTTPStatus(exc.status), str(exc))
            except Exception as exc:  # noqa: BLE001 - reported to the caller and the log
                self.log_message("unhandled %s %s: %r", self.command, urlsplit(self.path).path, exc)
                self.close_connection = True
                if not self._responded:
                    self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "The desktop runtime could not complete this request.")

        def _common_headers(self) -> None:
            self.send_header(SERVICE_HEADER, SERVICE_NAME)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            origin = self.headers.get("Origin")
            if origin == allowed_origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.send_header("Vary", "Origin")

        def _send_bytes(
            self,
            status: HTTPStatus,
            body: bytes,
            *,
            content_type: str = "application/json; charset=utf-8",
            headers: dict[str, str] | None = None,
        ) -> None:
            self._responded = True
            self.send_response(status)
            self._common_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_json(
            self,
            status: HTTPStatus,
            payload: dict[str, Any],
            *,
            headers: dict[str, str] | None = None,
        ) -> None:
            self._send_bytes(
                status,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                headers=headers,
            )

        def _error(self, status: HTTPStatus, message: str) -> None:
            # an error can leave part of a request body unread; never reuse the connection
            self.close_connection = True
            self._send_json(status, {"detail": message})

        def do_OPTIONS(self) -> None:  # noqa: N802
            if not self._is_allowed():
                self._error(HTTPStatus.FORBIDDEN, "Request origin or host not allowed")
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self._common_headers()
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                f"Accept, Content-Type, X-Filename, X-Relative-Path, {TOKEN_HEADER}",
            )
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_POST(self) -> None:  # noqa: N802
            if not self._is_allowed():
                self._error(HTTPStatus.FORBIDDEN, "Request origin or host not allowed")
                return
            if not self._has_token():
                self._error(HTTPStatus.UNAUTHORIZED, "Missing or invalid desktop API token")
                return
            self._guarded(self._route_post, urlsplit(self.path).path.rstrip("/") or "/")

        def _route_post(self, path: str) -> None:
            if path == "/ai/fault-detection/jobs":
                self._post_analysis_job()
                return
            if path == "/ai/fault-detection/datasets/imports":
                self._post_create_dataset_import()
                return
            if path == "/ai/fault-detection/training/jobs":
                self._post_training_job()
                return
            if path == "/ai/fault-detection/training/preview":
                self._post_training_preview()
                return
            dataset_prefix = "/ai/fault-detection/datasets/imports/"
            if path.startswith(dataset_prefix):
                remainder = path.removeprefix(dataset_prefix)
                if remainder.endswith("/files") and remainder.count("/") == 1:
                    self._post_dataset_file(remainder.removesuffix("/files"))
                    return
                if remainder.endswith("/complete") and remainder.count("/") == 1:
                    self._post_complete_dataset_import(remainder.removesuffix("/complete"))
                    return
                if remainder.endswith("/discard") and remainder.count("/") == 1:
                    self._send_json(HTTPStatus.OK, datasets().discard_import(remainder.removesuffix("/discard")))
                    return
                if remainder.endswith("/labels") and remainder.count("/") == 1:
                    self._post_dataset_label(remainder.removesuffix("/labels"))
                    return
            self._error(HTTPStatus.NOT_FOUND, "Not found")

        def _read_json_body(self, limit: int, too_large: str) -> dict[str, Any] | None:
            """The JSON object in the request body, or None after an error response."""
            media_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Expected application/json")
                return None
            try:
                length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                self._error(HTTPStatus.LENGTH_REQUIRED, "A valid Content-Length header is required")
                return None
            if length <= 0 or length > limit:
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, too_large)
                return None
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                payload = None
            if not isinstance(payload, dict):
                self._error(HTTPStatus.BAD_REQUEST, "The request body must be a JSON object")
                return None
            return payload

        def _post_training_job(self) -> None:
            service = training()
            payload = self._read_json_body(32 * 1024, "Training request is invalid or too large")
            if payload is None:
                return
            result = service.create_job(
                name=payload.get("name"),
                import_ids=payload.get("importIds"),
                epochs=payload.get("epochs"),
            )
            self._send_json(
                HTTPStatus.CREATED,
                result,
                headers={"Location": f"/ai/fault-detection/training/jobs/{result['jobId']}"},
            )

        def _post_training_preview(self) -> None:
            service = training()
            payload = self._read_json_body(32 * 1024, "Training preview request is invalid or too large")
            if payload is None:
                return
            self._send_json(HTTPStatus.OK, service.preview(payload.get("importIds")))

        def _post_analysis_job(self) -> None:
            if self.headers.get("Content-Encoding"):
                self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Compressed uploads are not supported")
                return
            media_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if media_type != "application/octet-stream":
                self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Expected application/octet-stream")
                return
            try:
                length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                self._error(HTTPStatus.LENGTH_REQUIRED, "A valid Content-Length header is required")
                return
            try:
                filename = unquote(self.headers.get("X-Filename") or "", encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, ValueError):
                self._error(HTTPStatus.BAD_REQUEST, "Invalid X-Filename header")
                return

            upload = None
            try:
                upload = job_service.begin_upload(filename, content_length=length)
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise JobServiceError("The upload ended before Content-Length.", 400)
                    job_service.write_upload(upload, chunk)
                    remaining -= len(chunk)
                job = job_service.finish_upload(upload)
            except JobServiceError as exc:
                if upload is not None and not upload.closed:
                    job_service.abort_upload(upload)
                self._error(HTTPStatus(exc.status), str(exc))
                return
            except Exception:
                if upload is not None and not upload.closed:
                    job_service.abort_upload(upload)
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to accept the PCAP upload")
                return
            self._send_json(
                HTTPStatus.ACCEPTED,
                job,
                headers={
                    "Location": f"/ai/fault-detection/jobs/{job['jobId']}",
                    "Retry-After": "1",
                },
            )

        def _post_create_dataset_import(self) -> None:
            service = datasets()
            payload = self._read_json_body(16 * 1024, "Dataset import metadata is invalid or too large")
            if payload is None:
                return
            created = service.create_import(
                str(payload.get("name") or ""),
                str(payload.get("sourceType") or ""),
            )
            self._send_json(
                HTTPStatus.CREATED,
                created,
                headers={"Location": f"/ai/fault-detection/datasets/imports/{created['importId']}"},
            )

        def _post_dataset_file(self, import_id: str) -> None:
            dataset_service = datasets()
            if self.headers.get("Content-Encoding"):
                self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Compressed HTTP uploads are not supported")
                return
            media_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if media_type != "application/octet-stream":
                self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Expected application/octet-stream")
                return
            try:
                length = int(self.headers.get("Content-Length") or "")
                filename = unquote(self.headers.get("X-Filename") or "", encoding="utf-8", errors="strict")
                relative_path = unquote(
                    self.headers.get("X-Relative-Path") or filename,
                    encoding="utf-8",
                    errors="strict",
                )
            except (UnicodeDecodeError, ValueError):
                self._error(HTTPStatus.BAD_REQUEST, "Invalid dataset upload headers")
                return
            upload = None
            try:
                upload = dataset_service.begin_upload(
                    import_id,
                    filename,
                    relative_path,
                    content_length=length,
                )
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise DatasetServiceError("The upload ended before Content-Length.", 400)
                    dataset_service.write_upload(upload, chunk)
                    remaining -= len(chunk)
                result = dataset_service.finish_upload(upload)
            except DatasetServiceError as exc:
                if upload is not None and not upload.closed:
                    dataset_service.abort_upload(upload)
                self._error(HTTPStatus(exc.status), str(exc))
                return
            except Exception:
                if upload is not None and not upload.closed:
                    dataset_service.abort_upload(upload)
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to accept the dataset upload")
                return
            self._send_json(HTTPStatus.ACCEPTED, result)

        def _post_complete_dataset_import(self, import_id: str) -> None:
            self._send_json(HTTPStatus.OK, datasets().complete_import(import_id))

        def _post_dataset_label(self, import_id: str) -> None:
            service = datasets()
            payload = self._read_json_body(64 * 1024, "Ground-truth label is invalid or too large")
            if payload is None:
                return
            result = service.save_label(
                import_id,
                digest=payload.get("sha256"),
                classification=payload.get("classification"),
                fault_family=payload.get("faultFamily"),
                reviewer=payload.get("reviewer"),
                notes=payload.get("notes"),
                expected_revision=payload.get("expectedRevision"),
            )
            self._send_json(HTTPStatus.OK, result)

        def do_GET(self) -> None:  # noqa: N802
            if not self._is_allowed():
                self._error(HTTPStatus.FORBIDDEN, "Request origin or host not allowed")
                return
            path = urlsplit(self.path).path.rstrip("/") or "/"
            if path != "/health" and not self._has_token():
                self._error(HTTPStatus.UNAUTHORIZED, "Missing or invalid desktop API token")
                return
            self._guarded(self._route_get, path)

        def _route_get(self, path: str) -> None:
            if path == "/health":
                health = job_service.health()
                self._send_json(
                    HTTPStatus.OK if health["ready"] else HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "service": SERVICE_NAME,
                        "status": "ok" if health["ready"] else "degraded",
                        "source": summary["source"],
                        "models": len(summary["leaderboard"]),
                        "sessions": summary["dataset"]["sessions"],
                        "inferenceReady": health["ready"],
                        # edition identity for the dashboard header
                        "productName": product_name,
                        "appVersion": app_version,
                        "summarySnapshotAt": summary.get("snapshotAt"),
                        # dataset import, ground truth and training: optional,
                        # never a reason to stop inference
                        "retraining": {
                            "available": dataset_service is not None and training_service is not None,
                            "reason": None if dataset_service is not None and training_service is not None else retraining_reason,
                        },
                        **health,
                    },
                )
                return
            if path == "/ai/fault-detection/summary":
                if self.headers.get("If-None-Match") == summary_etag:
                    self._responded = True
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    self._common_headers()
                    self.send_header("ETag", summary_etag)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._send_bytes(
                    HTTPStatus.OK,
                    summary_bytes,
                    headers={"ETag": summary_etag},
                )
                return
            if path == "/ai/fault-detection/datasets":
                self._send_json(HTTPStatus.OK, datasets().summary())
                return
            if path == "/ai/fault-detection/training":
                self._send_json(HTTPStatus.OK, training().summary())
                return
            training_prefix = "/ai/fault-detection/training/jobs/"
            if path.startswith(training_prefix):
                self._send_json(HTTPStatus.OK, training().get_job(path.removeprefix(training_prefix)))
                return
            dataset_prefix = "/ai/fault-detection/datasets/imports/"
            if path.startswith(dataset_prefix):
                remainder = path.removeprefix(dataset_prefix)
                if remainder.endswith("/labels") and remainder.count("/") == 1:
                    self._send_json(HTTPStatus.OK, datasets().label_batch(remainder.removesuffix("/labels")))
                    return
            prefix = "/ai/fault-detection/jobs/"
            if path.startswith(prefix):
                try:
                    job = job_service.get_job(path.removeprefix(prefix))
                except JobServiceError as exc:
                    self._error(HTTPStatus(exc.status), str(exc))
                    return
                self._send_json(HTTPStatus.OK, job)
                return
            self._error(HTTPStatus.NOT_FOUND, "Not found")

        def log_message(self, format: str, *args: Any) -> None:
            print(
                f"{self.address_string()} [{self.log_date_time_string()}] " + format % args,
                file=sys.stderr,
                flush=True,
            )

    return Handler


def _serve(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="imps-fault-runtime serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--tshark", required=True, type=Path)
    parser.add_argument("--jobs-root", required=True, type=Path)
    parser.add_argument("--datasets-root", type=Path, default=None)
    parser.add_argument("--training-root", type=Path, default=None)
    parser.add_argument("--training-worker", type=Path, default=None)
    parser.add_argument("--training-runtime-dir", type=Path, default=None)
    parser.add_argument("--training-python", type=Path, default=None)
    parser.add_argument("--training-ai-project", type=Path, default=None)
    parser.add_argument("--training-artifacts", type=Path, default=None)
    # Edition identity for /health. The Electron launcher passes it through the
    # environment (IMPS_PRODUCT_NAME / IMPS_APP_VERSION); the flags override it.
    parser.add_argument("--product-name", default=None)
    parser.add_argument("--app-version", default=None)
    # Development only: serve every route without the launch token.
    parser.add_argument("--no-api-token", action="store_true")
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("The desktop API can bind only to loopback")
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")

    origin = _validate_origin(args.origin)
    summary, summary_bytes, summary_etag = _load_summary(args.summary)
    # a summary whose policy the sidecar does not know is a broken build: stop
    # at once with the reason (it lands in desktop-runtime.log and Electron
    # reports the runtime exit) rather than run a detector the benchmark does
    # not describe
    try:
        policy_id = detection_policy.policy_id_from_summary(summary)
    except detection_policy.PolicyError as exc:
        raise SystemExit(f"Summary detectionPolicy is invalid: {exc}") from exc
    agentic_rank = next(
        (row.get("rank") for row in summary["leaderboard"]
         if isinstance(row, dict) and row.get("id") == "agentic-ai" and isinstance(row.get("rank"), int)),
        None,
    )
    service = PcapJobService(
        jobs_root=args.jobs_root,
        model_dir=args.model_dir,
        tshark=args.tshark,
        runtime_command=_runtime_command(),
        detection_policy=policy_id,
        benchmark_rank=agentic_rank,
    )
    # Read once and keep it out of every child process's environment. Without
    # one the routes are locked by a random token nobody knows (fail closed);
    # only an explicit --no-api-token serves them openly.
    api_token = os.environ.pop(TOKEN_ENV, "").strip() or None
    if args.no_api_token:
        api_token = None
        print(f"WARNING --no-api-token: every route is served without {TOKEN_HEADER}", file=sys.stderr, flush=True)
    elif api_token is None:
        api_token = secrets.token_hex(32)
        print(f"WARNING {TOKEN_ENV} is not set: every route but /health is locked", file=sys.stderr, flush=True)
    # Dataset import, ground truth and training are optional: a store that
    # cannot be used (moved behind a junction, unreadable) disables those
    # routes with the reason instead of taking PCAP inference down with it.
    dataset_service: TrainingDatasetService | None = None
    training_service: ModelTrainingService | None = None
    retraining_error = None
    source_runtime_dir = Path(__file__).resolve().parent
    try:
        dataset_service = TrainingDatasetService(
            args.datasets_root or (args.jobs_root.parent / "training-datasets")
        )
        training_service = ModelTrainingService(
            root=args.training_root or (args.jobs_root.parent / "model-training"),
            dataset_service=dataset_service,
            worker_script=args.training_worker or (source_runtime_dir.parent / "training" / "train_candidate.py"),
            portable_runtime_dir=args.training_runtime_dir or source_runtime_dir,
            tshark=args.tshark,
            base_model_dir=args.model_dir,
            python_executable=args.training_python,
            ai_project=args.training_ai_project,
            baseline_artifacts=args.training_artifacts,
        )
    except (DatasetServiceError, TrainingServiceError, OSError) as exc:
        dataset_service = training_service = None
        retraining_error = f"Dataset and training storage is unavailable: {exc}"
        print(f"WARNING {retraining_error}", file=sys.stderr, flush=True)
    handler = _make_handler(
        summary=summary,
        summary_bytes=summary_bytes,
        summary_etag=summary_etag,
        job_service=service,
        dataset_service=dataset_service,
        training_service=training_service,
        allowed_origin=origin,
        port=args.port,
        product_name=(args.product_name or os.environ.get("IMPS_PRODUCT_NAME") or "").strip() or None,
        app_version=(args.app_version or os.environ.get("IMPS_APP_VERSION") or "").strip() or None,
        api_token=api_token,
        retraining_error=retraining_error,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.daemon_threads = True

    def request_shutdown(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, request_shutdown)
        except (OSError, ValueError):
            pass
    print(
        f"READY http://127.0.0.1:{args.port} "
        f"models={len(summary['leaderboard'])} sessions={summary['dataset']['sessions']}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        if training_service is not None:
            training_service.shutdown()
        service.shutdown()
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"serve", "worker"}:
        raise SystemExit("Usage: imps-fault-runtime.exe {serve|worker} [options]")
    mode, argv = sys.argv[1], sys.argv[2:]
    if mode == "serve":
        return _serve(argv)
    from worker import main as worker_main

    sys.argv = [sys.argv[0], *argv]
    return worker_main()


if __name__ == "__main__":
    raise SystemExit(main())

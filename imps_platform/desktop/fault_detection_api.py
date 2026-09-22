"""Loopback-only API used by the iMPS Fault Detection desktop launcher.

It serves the verified full-fleet summary and isolated, asynchronous PCAP
inference jobs without requiring MongoDB or the full backend runtime.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import traceback
import types
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


SERVICE_HEADER = "X-iMPS-Desktop-Service"
SERVICE_NAME = "fault-detection"
ALLOWED_ORIGINS = {
    "http://localhost:3001",
    "http://127.0.0.1:3001",
}


def _load_results_module(project_root: Path):
    """Load the existing pure result loader without importing MongoDB config."""
    router_path = project_root / "backend" / "routers" / "fault_detection.py"
    if not router_path.is_file():
        raise RuntimeError(f"Fault-detection router not found: {router_path}")

    # The router's loader is standard-library-only, but the route itself imports
    # the auth dependency. A tiny module stub prevents config.py (and therefore
    # MongoDB) from loading in this deliberately local, read-only process.
    deps_stub = types.ModuleType("deps")

    class UserClaims:
        pass

    def get_current_user() -> None:
        return None

    deps_stub.UserClaims = UserClaims
    deps_stub.get_current_user = get_current_user
    sys.modules["deps"] = deps_stub

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    module_name = "imps_desktop_fault_detection_results"
    spec = importlib.util.spec_from_file_location(module_name, router_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load fault-detection router: {router_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    target = etag.removeprefix("W/")
    return any(
        candidate.strip() == "*"
        or candidate.strip().removeprefix("W/") == target
        for candidate in header.split(",")
    )


def _make_handler(results_module: Any, data_root: Path, job_service: Any, port: int):
    class FaultDetectionHandler(BaseHTTPRequestHandler):
        server_version = "iMPSFaultDetection/1.0"

        def _request_origin_is_allowed(self) -> bool:
            origin = self.headers.get("Origin")
            return origin is None or origin in ALLOWED_ORIGINS

        def _request_host_is_allowed(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in {
                f"localhost:{port}",
                f"127.0.0.1:{port}",
            }

        def _write_common_headers(self) -> None:
            self.send_header(SERVICE_HEADER, SERVICE_NAME)
            self.send_header("X-Content-Type-Options", "nosniff")
            origin = self.headers.get("Origin")
            if origin in ALLOWED_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.send_header("Vary", "Origin")

        def _send_json(
            self,
            status: HTTPStatus,
            payload: dict[str, Any],
            *,
            etag: str | None = None,
            cache_control: str = "no-store",
            headers: dict[str, str] | None = None,
        ) -> None:
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            self.send_response(status)
            self._write_common_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache_control)
            if etag:
                self.send_header("ETag", etag)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_not_modified(self, etag: str) -> None:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self._write_common_headers()
            self.send_header("Cache-Control", "private, max-age=60")
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_error_json(self, status: HTTPStatus, detail: str) -> None:
            self._send_json(status, {"detail": detail})

        def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
            if not self._request_host_is_allowed() or not self._request_origin_is_allowed():
                self._send_error_json(HTTPStatus.FORBIDDEN, "Request origin or host not allowed")
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self._write_common_headers()
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Accept, Content-Type, X-Filename")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
            self.do_GET()

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            if not self._request_host_is_allowed() or not self._request_origin_is_allowed():
                self._send_error_json(HTTPStatus.FORBIDDEN, "Request origin or host not allowed")
                return
            path = urlsplit(self.path).path.rstrip("/") or "/"
            if path != "/ai/fault-detection/jobs":
                self._send_error_json(HTTPStatus.NOT_FOUND, "Not found")
                return
            if self.headers.get("Content-Encoding"):
                self._send_error_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Compressed request bodies are not supported")
                return
            content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type != "application/octet-stream":
                self._send_error_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Expected application/octet-stream")
                return
            try:
                content_length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                self._send_error_json(HTTPStatus.LENGTH_REQUIRED, "A valid Content-Length header is required")
                return
            try:
                filename = unquote(
                    self.headers.get("X-Filename") or "",
                    encoding="utf-8",
                    errors="strict",
                )
            except (UnicodeDecodeError, ValueError):
                self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid X-Filename header")
                return

            upload = None
            try:
                upload = job_service.begin_upload(filename, content_length=content_length)
                remaining = content_length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise results_module.JobServiceError(
                            "The upload ended before the declared Content-Length.", 400
                        )
                    job_service.write_upload(upload, chunk)
                    remaining -= len(chunk)
                job = job_service.finish_upload(upload)
            except results_module.JobServiceError as exc:
                if upload is not None and not upload.closed:
                    job_service.abort_upload(upload)
                self._send_error_json(HTTPStatus(exc.status), str(exc))
                return
            except Exception:
                if upload is not None and not upload.closed:
                    job_service.abort_upload(upload)
                traceback.print_exc(file=sys.stderr)
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to accept the PCAP upload")
                return
            self._send_json(
                HTTPStatus.ACCEPTED,
                job,
                headers={
                    "Location": f"/ai/fault-detection/jobs/{job['jobId']}",
                    "Retry-After": "1",
                },
            )

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if not self._request_host_is_allowed() or not self._request_origin_is_allowed():
                self._send_error_json(HTTPStatus.FORBIDDEN, "Request origin or host not allowed")
                return

            path = urlsplit(self.path).path.rstrip("/") or "/"
            if path == "/health":
                try:
                    summary, _ = results_module.load_fault_detection_summary(data_root)
                except Exception:
                    self._send_error_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        "Benchmark results are unavailable or invalid",
                    )
                    return
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "service": SERVICE_NAME,
                        "status": "ok",
                        "source": summary["source"],
                        "models": len(summary["leaderboard"]),
                        "sessions": summary["dataset"]["sessions"],
                        "inferenceReady": job_service.health()["ready"],
                        "maxUploadBytes": job_service.health()["maxUploadBytes"],
                    },
                )
                return

            job_prefix = "/ai/fault-detection/jobs/"
            if path.startswith(job_prefix):
                job_id = path.removeprefix(job_prefix)
                try:
                    job = job_service.get_job(job_id)
                except results_module.JobServiceError as exc:
                    self._send_error_json(HTTPStatus(exc.status), str(exc))
                    return
                self._send_json(HTTPStatus.OK, job)
                return

            if path != "/ai/fault-detection/summary":
                self._send_error_json(HTTPStatus.NOT_FOUND, "Not found")
                return

            try:
                summary, etag = results_module.load_fault_detection_summary(data_root)
            except results_module.FaultDetectionResultError as exc:
                print(f"Result validation failed: {exc}", file=sys.stderr, flush=True)
                self._send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Full-fleet benchmark results are unavailable or invalid",
                )
                return
            except Exception:
                traceback.print_exc(file=sys.stderr)
                self._send_error_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "Unable to load full-fleet benchmark results",
                )
                return

            if _etag_matches(self.headers.get("If-None-Match"), etag):
                self._send_not_modified(etag)
                return
            self._send_json(
                HTTPStatus.OK,
                summary,
                etag=etag,
                cache_control="private, max-age=60, stale-while-revalidate=300",
            )

        def log_message(self, format: str, *args: Any) -> None:
            print(
                f"{self.address_string()} [{self.log_date_time_string()}] "
                + (format % args),
                file=sys.stderr,
                flush=True,
            )

    return FaultDetectionHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--data-root", type=Path, default=Path(r"G:\ev_charger_ai_data_v4"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Desktop API must bind to the local loopback interface")
    if not 1 <= args.port <= 65535:
        raise SystemExit("Port must be between 1 and 65535")

    project_root = Path(__file__).resolve().parent.parent
    results_module = _load_results_module(project_root)
    jobs_root = (
        Path(os.environ.get("LOCALAPPDATA", str(project_root)))
        / "iMPS-FaultDetection"
        / "jobs"
        / "desktop"
    )
    job_service = results_module.PcapJobService(
        project_root=project_root,
        data_root=args.data_root,
        jobs_root=jobs_root,
    )

    # Validate once before opening the socket so the launcher never reports a
    # ready service while the expected full-fleet artifacts are missing.
    summary, _ = results_module.load_fault_detection_summary(args.data_root)
    handler = _make_handler(results_module, args.data_root, job_service, args.port)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.daemon_threads = True
    print(
        f"READY http://localhost:{args.port} "
        f"models={len(summary['leaderboard'])} "
        f"sessions={summary['dataset']['sessions']}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

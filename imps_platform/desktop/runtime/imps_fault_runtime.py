"""Portable loopback API and PCAP inference worker for iMPS desktop."""

from __future__ import annotations

import argparse
import hashlib
import json
import signal
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from job_service import JobServiceError, PcapJobService


SERVICE_NAME = "fault-detection-portable"
SERVICE_HEADER = "X-iMPS-Desktop-Service"


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
    allowed_origin: str,
    port: int,
):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "iMPSFaultRuntime/1.0"

        def _is_allowed(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            origin = self.headers.get("Origin")
            return host in allowed_hosts and (origin is None or origin == allowed_origin)

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
            self._send_json(status, {"detail": message})

        def do_OPTIONS(self) -> None:  # noqa: N802
            if not self._is_allowed():
                self._error(HTTPStatus.FORBIDDEN, "Request origin or host not allowed")
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self._common_headers()
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Accept, Content-Type, X-Filename")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_POST(self) -> None:  # noqa: N802
            if not self._is_allowed():
                self._error(HTTPStatus.FORBIDDEN, "Request origin or host not allowed")
                return
            if urlsplit(self.path).path.rstrip("/") != "/ai/fault-detection/jobs":
                self._error(HTTPStatus.NOT_FOUND, "Not found")
                return
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

        def do_GET(self) -> None:  # noqa: N802
            if not self._is_allowed():
                self._error(HTTPStatus.FORBIDDEN, "Request origin or host not allowed")
                return
            path = urlsplit(self.path).path.rstrip("/") or "/"
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
                        **health,
                    },
                )
                return
            if path == "/ai/fault-detection/summary":
                if self.headers.get("If-None-Match") == summary_etag:
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
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("The desktop API can bind only to loopback")
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")

    origin = _validate_origin(args.origin)
    summary, summary_bytes, summary_etag = _load_summary(args.summary)
    service = PcapJobService(
        jobs_root=args.jobs_root,
        model_dir=args.model_dir,
        tshark=args.tshark,
        runtime_command=_runtime_command(),
    )
    handler = _make_handler(
        summary=summary,
        summary_bytes=summary_bytes,
        summary_etag=summary_etag,
        job_service=service,
        allowed_origin=origin,
        port=args.port,
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

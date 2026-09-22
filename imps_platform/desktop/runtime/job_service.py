
"""Disk-backed, single-worker PCAP inference jobs.

The module deliberately uses only the Python standard library so it can be
shared by the normal FastAPI application and the lightweight desktop server.
Uploaded capture data is never used as a path or as executable input.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


MAX_UPLOAD_BYTES = 256 * 1024 * 1024
MAX_QUEUED_JOBS = 4
INFERENCE_TIMEOUT_SECONDS = 30 * 60
MAX_RESULT_BYTES = 10 * 1024 * 1024
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
CAPTURE_MAGIC = {
    b"\xd4\xc3\xb2\xa1": ("pcap", 24),
    b"\xa1\xb2\xc3\xd4": ("pcap", 24),
    b"\x4d\x3c\xb2\xa1": ("pcap", 24),
    b"\xa1\xb2\x3c\x4d": ("pcap", 24),
    b"\x0a\x0d\x0d\x0a": ("pcapng", 12),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


class JobServiceError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class UploadHandle:
    job_id: str
    job_dir: Path
    temporary_path: Path
    final_path: Path
    state_path: Path
    original_name: str
    owner: str | None
    expected_size: int | None
    handle: Any
    digest: Any
    size_bytes: int = 0
    closed: bool = False


class PcapJobService:
    def __init__(
        self,
        *,
        jobs_root: Path,
        model_dir: Path,
        tshark: Path,
        runtime_command: list[str],
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
        max_queued_jobs: int = MAX_QUEUED_JOBS,
        timeout_seconds: int = INFERENCE_TIMEOUT_SECONDS,
        retention_days: int = 30,
    ) -> None:
        self.jobs_root = jobs_root.resolve()
        self.model_dir = model_dir.resolve()
        self.tshark = tshark.resolve()
        self.runtime_command = list(runtime_command)
        if not self.runtime_command:
            raise ValueError("runtime_command cannot be empty")
        self.max_upload_bytes = max_upload_bytes
        self.max_queued_jobs = max_queued_jobs
        self.timeout_seconds = timeout_seconds
        self.retention_days = max(1, retention_days)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pcap-ai")
        self._lock = threading.RLock()
        self._uploads: set[str] = set()
        self._futures: dict[str, Future[Any]] = {}
        self._processes: dict[str, subprocess.Popen[Any]] = {}
        self._closed = False
        # Identity of the bundled model, reported on /health so the dashboard
        # can show which edition is running. Filled in by _validate_dependencies.
        self.model_info: dict[str, Any] = {"artifactVersion": None, "createdAt": None}
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self._recover_interrupted_jobs()
        self._cleanup_expired_jobs()
        self._dependency_errors = self._validate_dependencies()

    def health(self) -> dict[str, Any]:
        return {
            "ready": not self._dependency_errors,
            "missing": list(self._dependency_errors),
            "artifactVersion": self.model_info["artifactVersion"],
            "modelCreatedAt": self.model_info["createdAt"],
            "maxUploadBytes": self.max_upload_bytes,
            "maxQueuedJobs": self.max_queued_jobs,
            "retentionDays": self.retention_days,
        }

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _validate_dependencies(self) -> list[str]:
        """Deep-check models, hashes, NumPy loading, and the V2G dissector."""
        errors: list[str] = []
        paths = (
            self.model_dir / "lstm_ae.npz",
            self.model_dir / "gru_fore.npz",
            self.model_dir / "manifest.json",
            self.tshark,
        )
        errors.extend(str(path) for path in paths if not path.is_file())
        if errors:
            return errors
        try:
            manifest = _load_json(self.model_dir / "manifest.json")
            if not isinstance(manifest.get("artifactVersion"), str):
                raise ValueError("artifactVersion is missing")
            files = manifest.get("files")
            if not isinstance(files, dict):
                raise ValueError("file hashes are missing")
            for name in ("lstm_ae.npz", "gru_fore.npz"):
                expected = (files.get(name) or {}).get("sha256")
                if expected != self._sha256_file(self.model_dir / name):
                    raise ValueError(f"hash mismatch for {name}")
            created_at = manifest.get("createdAt")
            self.model_info = {
                "artifactVersion": manifest["artifactVersion"],
                "createdAt": created_at if isinstance(created_at, str) else None,
            }

            import numpy as np

            required = {
                "lstm_ae.npz": {
                    "__err_mean", "__err_std", "__n_feat",
                    "enc.weight_ih_l0", "dec.weight_ih_l0", "out.weight",
                },
                "gru_fore.npz": {
                    "__err_mean", "__err_std", "gru.weight_ih_l0", "head.weight",
                },
            }
            for name, keys in required.items():
                with np.load(self.model_dir / name, allow_pickle=False) as archive:
                    missing = keys.difference(archive.files)
                    if missing:
                        raise ValueError(f"{name} lacks {', '.join(sorted(missing))}")
                    for key in keys:
                        np.asarray(archive[key])
        except Exception as exc:
            errors.append(f"model validation: {exc}")

        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            version = subprocess.run(
                [str(self.tshark), "--version"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # First launch can be delayed substantially while endpoint
                # protection scans the newly installed Wireshark binaries.
                timeout=60,
                check=False,
                creationflags=creation_flags,
            )
            if version.returncode != 0 or b"TShark" not in version.stdout:
                raise RuntimeError("tshark --version failed")
            fields = subprocess.run(
                [str(self.tshark), "-G", "fields"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
                creationflags=creation_flags,
            )
            if fields.returncode != 0 or b"v2gmsg.msgname" not in fields.stdout:
                raise RuntimeError("V2G Lua dissector field v2gmsg.msgname is unavailable")
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            errors.append(f"tshark validation: {exc}")
        return errors

    def _recover_interrupted_jobs(self) -> None:
        """Mark work left in-flight by a previous process as safely failed."""
        for state_path in self.jobs_root.glob("*/state.json"):
            try:
                state = _load_json(state_path)
                if state.get("status") not in {"queued", "processing"}:
                    continue
                state.update(
                    status="failed",
                    stage="failed",
                    progress=100.0,
                    completedAt=utc_now(),
                    error="Analysis was interrupted because the application closed.",
                    workerPid=None,
                )
                _write_json_atomic(state_path, state)
            except (OSError, ValueError, json.JSONDecodeError):
                continue

    def _cleanup_expired_jobs(self) -> None:
        cutoff = time.time() - self.retention_days * 24 * 60 * 60
        for job_dir in self.jobs_root.iterdir():
            try:
                resolved = job_dir.resolve()
                if (
                    not job_dir.is_dir()
                    or resolved.parent != self.jobs_root
                    or not JOB_ID_RE.fullmatch(job_dir.name)
                ):
                    continue
                state_path = resolved / "state.json"
                if state_path.stat().st_mtime < cutoff:
                    shutil.rmtree(resolved)
            except OSError:
                continue

    @staticmethod
    def validate_filename(filename: str) -> tuple[str, str]:
        name = filename.strip()
        if not name or len(name) > 200:
            raise JobServiceError("The capture filename is missing or too long.", 400)
        if any(ord(character) < 32 for character in name):
            raise JobServiceError("The capture filename contains control characters.", 400)
        if Path(name).name != name or "/" in name or "\\" in name:
            raise JobServiceError("The capture filename must not contain a path.", 400)
        extension = Path(name).suffix.lower()
        if extension not in {".pcap", ".pcapng"}:
            raise JobServiceError("Only .pcap and .pcapng capture files are supported.", 415)
        return name, extension

    def _active_count(self) -> int:
        self._futures = {
            job_id: future
            for job_id, future in self._futures.items()
            if not future.done()
        }
        return len(self._uploads) + len(self._futures)

    def begin_upload(
        self,
        filename: str,
        *,
        content_length: int | None = None,
        owner: str | None = None,
    ) -> UploadHandle:
        if self._closed:
            raise JobServiceError("PCAP analysis service is shutting down.", 503)
        original_name, extension = self.validate_filename(filename)
        if content_length is not None:
            if content_length <= 0:
                raise JobServiceError("The uploaded capture is empty.", 400)
            if content_length > self.max_upload_bytes:
                raise JobServiceError(
                    f"The capture exceeds the {self.max_upload_bytes // (1024 * 1024)} MiB limit.",
                    413,
                )
        readiness = self.health()
        if not readiness["ready"]:
            raise JobServiceError("PCAP inference dependencies are unavailable.", 503)
        free_bytes = shutil.disk_usage(self.jobs_root).free
        required = (content_length or self.max_upload_bytes) + 128 * 1024 * 1024
        if free_bytes < required:
            raise JobServiceError("There is not enough local disk space for this analysis.", 507)

        with self._lock:
            if self._active_count() >= self.max_queued_jobs:
                raise JobServiceError("The PCAP analysis queue is full. Please try again later.", 429)
            job_id = uuid.uuid4().hex
            job_dir = (self.jobs_root / job_id).resolve()
            if job_dir.parent != self.jobs_root:
                raise JobServiceError("Unable to allocate a safe job directory.", 500)
            job_dir.mkdir(parents=False, exist_ok=False)
            temporary_path = job_dir / f"input{extension}.upload"
            final_path = job_dir / f"input{extension}"
            upload = UploadHandle(
                job_id=job_id,
                job_dir=job_dir,
                temporary_path=temporary_path,
                final_path=final_path,
                state_path=job_dir / "state.json",
                original_name=original_name,
                owner=owner,
                expected_size=content_length,
                handle=temporary_path.open("xb"),
                digest=sha256(),
            )
            self._uploads.add(job_id)
            return upload

    def write_upload(self, upload: UploadHandle, chunk: bytes) -> None:
        if upload.closed:
            raise JobServiceError("The upload is already closed.", 409)
        if not chunk:
            return
        next_size = upload.size_bytes + len(chunk)
        if next_size > self.max_upload_bytes:
            self.abort_upload(upload)
            raise JobServiceError(
                f"The capture exceeds the {self.max_upload_bytes // (1024 * 1024)} MiB limit.",
                413,
            )
        upload.handle.write(chunk)
        upload.digest.update(chunk)
        upload.size_bytes = next_size

    def finish_upload(self, upload: UploadHandle) -> dict[str, Any]:
        if upload.closed:
            raise JobServiceError("The upload is already closed.", 409)
        upload.handle.flush()
        os.fsync(upload.handle.fileno())
        upload.handle.close()
        upload.closed = True
        try:
            if upload.size_bytes == 0:
                raise JobServiceError("The uploaded capture is empty.", 400)
            if upload.expected_size is not None and upload.size_bytes != upload.expected_size:
                raise JobServiceError("The upload ended before the declared Content-Length.", 400)
            with upload.temporary_path.open("rb") as handle:
                magic = handle.read(4)
            capture = CAPTURE_MAGIC.get(magic)
            if capture is None:
                raise JobServiceError("The file does not have a valid PCAP or PCAPNG header.", 422)
            if upload.size_bytes < capture[1]:
                raise JobServiceError("The packet capture header is truncated.", 422)
            expected_format = "pcapng" if upload.final_path.suffix.lower() == ".pcapng" else "pcap"
            if capture[0] != expected_format:
                raise JobServiceError("The capture extension does not match its file format.", 422)

            os.replace(upload.temporary_path, upload.final_path)
            state = {
                "schemaVersion": 1,
                "jobId": upload.job_id,
                "status": "queued",
                "stage": "queued",
                "progress": 3.0,
                "createdAt": utc_now(),
                "startedAt": None,
                "completedAt": None,
                "originalName": upload.original_name,
                "sizeBytes": upload.size_bytes,
                "sha256": upload.digest.hexdigest(),
                "error": None,
                "owner": upload.owner,
                "inputPath": str(upload.final_path),
            }
            _write_json_atomic(upload.state_path, state)
            with self._lock:
                self._uploads.discard(upload.job_id)
                self._futures[upload.job_id] = self._executor.submit(
                    self._run_job, upload.job_id
                )
            return self.get_job(upload.job_id, owner=upload.owner)
        except Exception:
            with self._lock:
                self._uploads.discard(upload.job_id)
            if upload.temporary_path.exists():
                upload.temporary_path.unlink()
            if not upload.state_path.exists():
                try:
                    upload.job_dir.rmdir()
                except OSError:
                    pass
            raise

    def abort_upload(self, upload: UploadHandle) -> None:
        if not upload.closed:
            upload.handle.close()
            upload.closed = True
        with self._lock:
            self._uploads.discard(upload.job_id)
        if upload.temporary_path.exists():
            upload.temporary_path.unlink()
        try:
            upload.job_dir.rmdir()
        except OSError:
            pass

    def _job_dir(self, job_id: str) -> Path:
        if not JOB_ID_RE.fullmatch(job_id):
            raise JobServiceError("Analysis job not found.", 404)
        job_dir = (self.jobs_root / job_id).resolve()
        if job_dir.parent != self.jobs_root:
            raise JobServiceError("Analysis job not found.", 404)
        return job_dir

    def _update_state(self, job_id: str, **updates: Any) -> dict[str, Any]:
        path = self._job_dir(job_id) / "state.json"
        with self._lock:
            state = _load_json(path)
            state.update(updates)
            _write_json_atomic(path, state)
            return state

    def _run_job(self, job_id: str) -> None:
        job_dir = self._job_dir(job_id)
        state_path = job_dir / "state.json"
        try:
            state = _load_json(state_path)
            self._update_state(
                job_id,
                status="processing",
                stage="starting",
                progress=5.0,
                startedAt=utc_now(),
                workerPid=None,
            )
            command = [
                *self.runtime_command,
                "worker",
                "--input",
                state["inputPath"],
                "--output",
                str(job_dir / "result.json"),
                "--progress",
                str(job_dir / "progress.json"),
                "--model-dir",
                str(self.model_dir),
                "--tshark",
                str(self.tshark),
                "--original-name",
                state["originalName"],
                "--sha256",
                state["sha256"],
            ]
            creation_flags = 0
            if os.name == "nt":
                creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            with (job_dir / "worker.stdout.log").open("wb") as stdout_handle, (
                job_dir / "worker.stderr.log"
            ).open("wb") as stderr_handle:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    shell=False,
                    cwd=str(job_dir),
                    creationflags=creation_flags,
                )
                with self._lock:
                    self._processes[job_id] = process
                self._update_state(job_id, workerPid=process.pid)
                try:
                    return_code = process.wait(timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired as exc:
                    self._terminate_worker_tree(process)
                    raise RuntimeError(
                        f"PCAP analysis exceeded the {self.timeout_seconds // 60}-minute timeout."
                    ) from exc
                finally:
                    with self._lock:
                        self._processes.pop(job_id, None)
            if return_code != 0:
                stderr = (job_dir / "worker.stderr.log").read_text(
                    encoding="utf-8", errors="replace"
                )
                useful = [line.strip() for line in stderr.splitlines() if line.strip()]
                message = useful[-1][:400] if useful else f"AI worker exited with code {return_code}."
                raise RuntimeError(message)
            result_path = job_dir / "result.json"
            if not result_path.is_file() or result_path.stat().st_size == 0:
                raise RuntimeError("The AI worker completed without a result.")
            if result_path.stat().st_size > MAX_RESULT_BYTES:
                raise RuntimeError("The AI worker result exceeds the safety limit.")
            result = _load_json(result_path)
            if result.get("schemaVersion") != 1:
                raise RuntimeError("The AI worker returned an unsupported result schema.")
            self._update_state(
                job_id,
                status="complete",
                stage="complete",
                progress=100.0,
                completedAt=utc_now(),
                error=None,
                workerPid=None,
            )
        except Exception as exc:
            try:
                self._update_state(
                    job_id,
                    status="failed",
                    stage="failed",
                    progress=100.0,
                    completedAt=utc_now(),
                    error=str(exc)[:500] or "PCAP analysis failed.",
                    workerPid=None,
                )
            except Exception:
                pass
        finally:
            # Raw captures and decoded telemetry are no longer needed once a
            # result or failure state exists.  Keep only the small audit/result
            # records; these are purged by the bounded retention policy.
            for pattern in ("input.pcap", "input.pcapng", "telemetry.csv", "telemetry.meta.json"):
                path = job_dir / pattern
                try:
                    if path.is_file():
                        path.unlink()
                except OSError:
                    pass

    def shutdown(self) -> None:
        """Stop accepting work and terminate only workers spawned by us."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            processes = list(self._processes.values())
        for process in processes:
            self._terminate_worker_tree(process)
        self._executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _terminate_worker_tree(process: subprocess.Popen[Any]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=20,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            process.kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    def get_job(self, job_id: str, *, owner: str | None = None) -> dict[str, Any]:
        job_dir = self._job_dir(job_id)
        state_path = job_dir / "state.json"
        if not state_path.is_file():
            raise JobServiceError("Analysis job not found.", 404)
        try:
            state = _load_json(state_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise JobServiceError("Analysis job state is unavailable.", 503) from exc
        stored_owner = state.get("owner")
        if stored_owner is not None and owner != stored_owner:
            raise JobServiceError("Analysis job not found.", 404)

        progress_path = job_dir / "progress.json"
        if state.get("status") == "processing" and progress_path.is_file():
            try:
                progress = _load_json(progress_path)
                state["stage"] = str(progress.get("stage") or state["stage"])
                state["progress"] = max(
                    float(state.get("progress") or 0),
                    min(99.0, float(progress.get("progress") or 0)),
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass

        public_keys = (
            "schemaVersion",
            "jobId",
            "status",
            "stage",
            "progress",
            "createdAt",
            "startedAt",
            "completedAt",
            "originalName",
            "sizeBytes",
            "sha256",
            "error",
        )
        public = {key: state.get(key) for key in public_keys}
        result_path = job_dir / "result.json"
        public["result"] = (
            _load_json(result_path)
            if state.get("status") == "complete" and result_path.is_file()
            else None
        )
        return public


__all__ = [
    "JobServiceError",
    "MAX_UPLOAD_BYTES",
    "PcapJobService",
    "UploadHandle",
]

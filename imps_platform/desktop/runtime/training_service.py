"""Disk-backed candidate-model training jobs for the Desktop application.

The installed inference sidecar intentionally stays NumPy-only.  Training is
delegated to a separately installed, explicitly validated PyTorch environment
and every run writes a new candidate directory; it never modifies the model
bundled with the running application.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataset_service import DatasetServiceError, TrainingDatasetService


JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_JOBS_RETURNED = 20
MAX_IMPORTS_PER_JOB = 24
MAX_EPOCHS = 8
MAX_TRAINING_CAPTURE_BYTES = 4 * 1024 * 1024 * 1024
TRAINING_TIMEOUT_SECONDS = 8 * 60 * 60
ENGINE_CONFIG_NAME = "engine.json"
# Where the external PyTorch engine lives, by precedence: command line,
# environment, <training root>/engine.json, then the research workstation layout.
ENGINE_SETTINGS = {
    "python": ("IMPS_TRAINING_PYTHON", lambda: Path.home() / "anaconda3" / "envs" / "ev_ai" / "python.exe"),
    "aiProject": ("IMPS_TRAINING_AI_PROJECT", lambda: Path(r"F:\pcap_downloads\ev_charger_ai_v4_original_snapshot")),
    "baselineArtifacts": ("IMPS_TRAINING_ARTIFACTS", lambda: Path(r"G:\ev_charger_ai_data_v4\artifacts")),
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
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected an object")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_artifact_version(source: Path) -> str:
    digest = hashlib.sha256()
    for name in ("lstm_ae.pt", "gru_fore.pt"):
        path = source / name
        digest.update(name.encode("ascii"))
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()[:16]


def _is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if path.is_symlink():
        return True
    reparse_flag = getattr(metadata, "st_file_attributes", 0)
    return bool(reparse_flag & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


class TrainingServiceError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class ModelTrainingService:
    """Queue one reproducible candidate-model training run at a time."""

    def __init__(
        self,
        *,
        root: Path,
        dataset_service: TrainingDatasetService,
        worker_script: Path,
        portable_runtime_dir: Path,
        tshark: Path,
        base_model_dir: Path,
        python_executable: Path | None = None,
        ai_project: Path | None = None,
        baseline_artifacts: Path | None = None,
        timeout_seconds: int = TRAINING_TIMEOUT_SECONDS,
    ) -> None:
        requested_root = root.absolute()
        if any(path.exists() and _is_link_like(path) for path in (requested_root, requested_root / "jobs")):
            raise TrainingServiceError("The model-training storage path is unsafe.", 503)
        self.root = root.resolve()
        self.jobs_root = self.root / "jobs"
        self.dataset_service = dataset_service
        self.worker_script = worker_script.resolve()
        self.portable_runtime_dir = portable_runtime_dir.resolve()
        self.tshark = tshark.resolve()
        self.base_model_dir = base_model_dir.resolve()
        self._cli_engine = {
            "python": python_executable,
            "aiProject": ai_project,
            "baselineArtifacts": baseline_artifacts,
        }
        self.config_path = self.root / ENGINE_CONFIG_NAME
        self.timeout_seconds = timeout_seconds
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._version_cache: tuple[tuple[Any, ...], str] | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-training")
        self._futures: dict[str, Future[Any]] = {}
        self._processes: dict[str, subprocess.Popen[Any]] = {}
        self._shutting_down = False
        self._recover_interrupted_jobs()

    def _engine_config(self) -> tuple[dict[str, Path], dict[str, str], str | None]:
        """Resolve the external engine paths now, so editing engine.json needs no restart."""
        file_values: dict[str, Any] = {}
        config_error = None
        try:
            if self.config_path.is_file() and not _is_link_like(self.config_path):
                file_values = _load_json(self.config_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            config_error = f"{ENGINE_CONFIG_NAME} could not be read: {exc}"[:300]
        paths: dict[str, Path] = {}
        sources: dict[str, str] = {}
        for key, (env_name, default) in ENGINE_SETTINGS.items():
            cli_value = self._cli_engine.get(key)
            env_value = os.environ.get(env_name, "").strip()
            file_value = file_values.get(key)
            if cli_value is not None:
                paths[key], sources[key] = Path(cli_value), "command_line"
            elif env_value:
                paths[key], sources[key] = Path(env_value), "environment"
            elif isinstance(file_value, str) and file_value.strip():
                paths[key], sources[key] = Path(file_value.strip()), "config_file"
            else:
                paths[key], sources[key] = default(), "default"
            paths[key] = paths[key].expanduser().absolute()
        return paths, sources, config_error

    @property
    def python_executable(self) -> Path:
        return self._engine_config()[0]["python"]

    @property
    def ai_project(self) -> Path:
        return self._engine_config()[0]["aiProject"]

    @property
    def baseline_artifacts(self) -> Path:
        return self._engine_config()[0]["baselineArtifacts"]

    def _checkpoint_version(self, artifacts: Path) -> str:
        """_source_artifact_version, cached on size and mtime: health is polled."""
        key = tuple(
            (str(artifacts / name), (artifacts / name).stat().st_size, (artifacts / name).stat().st_mtime_ns)
            for name in ("lstm_ae.pt", "gru_fore.pt")
        )
        cached = self._version_cache
        if cached and cached[0] == key:
            return cached[1]
        version = _source_artifact_version(artifacts)
        self._version_cache = (key, version)
        return version

    def health(self) -> dict[str, Any]:
        paths, sources, config_error = self._engine_config()
        ai_project = paths["aiProject"]
        artifacts = paths["baselineArtifacts"]

        def requirement(identifier: str, label: str, path: Path | None, files: list[Path]) -> dict[str, Any]:
            return {
                "id": identifier,
                "label": label,
                "path": str(path) if path is not None else None,
                "ok": all(item.is_file() for item in files),
            }

        requirements = [
            requirement("python", "Python interpreter with PyTorch", paths["python"], [paths["python"]]),
            requirement(
                "aiProject",
                "Research project (models/nn_tools.py, core/feature_tracker.py, core/schema.py)",
                ai_project,
                [ai_project / "models" / "nn_tools.py", ai_project / "core" / "feature_tracker.py", ai_project / "core" / "schema.py"],
            ),
            requirement(
                "baselineArtifacts",
                "Baseline checkpoints (lstm_ae.pt, gru_fore.pt)",
                artifacts,
                [artifacts / "lstm_ae.pt", artifacts / "gru_fore.pt"],
            ),
            requirement("worker", "Training worker (bundled)", self.worker_script, [self.worker_script]),
            requirement(
                "decoder",
                "Capture decoder (bundled)",
                self.portable_runtime_dir / "capture.py",
                [self.portable_runtime_dir / "capture.py"],
            ),
            requirement("tshark", "TShark (bundled)", self.tshark, [self.tshark]),
            requirement(
                "baseModel",
                "Installed model manifest (bundled)",
                self.base_model_dir / "manifest.json",
                [self.base_model_dir / "manifest.json"],
            ),
        ]
        match = {"id": "baselineMatch", "label": "Baseline checkpoints match the installed model", "path": None, "ok": False}
        if all(item["ok"] for item in requirements):
            try:
                match["ok"] = self._base_version() == self._checkpoint_version(artifacts)
                if not match["ok"]:
                    match["detail"] = "The external baseline checkpoints do not match the installed model."
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                match["detail"] = "The baseline model manifest or checkpoints are invalid."
        else:
            match["detail"] = "Checked once every file above is present."
        requirements.append(match)
        missing = [
            item.get("detail") or item["path"] or item["label"]
            for item in requirements
            if not item["ok"]
        ]
        if config_error:
            missing.insert(0, config_error)
        return {
            "available": not missing,
            "mode": "external_pytorch",
            "device": "auto_cuda_or_cpu",
            "missing": missing,
            "requirements": requirements,
            "configFile": str(self.config_path),
            "configSource": sources,
            "configError": config_error,
            "maxEpochs": MAX_EPOCHS,
        }

    def _base_version(self) -> str:
        manifest = _load_json(self.base_model_dir / "manifest.json")
        version = manifest.get("artifactVersion")
        if not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{16}", version):
            raise ValueError("invalid base artifact version")
        return version

    def _job_dir(self, job_id: str, *, must_exist: bool = True) -> Path:
        if not JOB_ID_RE.fullmatch(job_id):
            raise TrainingServiceError("Training job not found.", 404)
        candidate = self.jobs_root / job_id
        if _is_link_like(candidate):
            raise TrainingServiceError("Training job not found.", 404)
        if must_exist and not candidate.is_dir():
            raise TrainingServiceError("Training job not found.", 404)
        return candidate

    def _state_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "state.json"

    def _read_state(self, job_id: str) -> dict[str, Any]:
        try:
            return _load_json(self._state_path(job_id))
        except FileNotFoundError as exc:
            raise TrainingServiceError("Training job not found.", 404) from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise TrainingServiceError("Training job state is unavailable.", 503) from exc

    def _update_state(self, job_id: str, **updates: Any) -> dict[str, Any]:
        with self._lock:
            state = self._read_state(job_id)
            state.update(updates)
            _write_json_atomic(self._state_path(job_id), state)
            return state

    @staticmethod
    def _remove_work_dir(job_dir: Path) -> None:
        """Decoded telemetry is as large as the captures; it never outlives a run."""
        work_dir = job_dir / "work"
        if _is_link_like(work_dir):
            try:
                os.unlink(work_dir) if work_dir.is_symlink() else os.rmdir(work_dir)
            except OSError:
                pass
            return
        if work_dir.is_dir():
            shutil.rmtree(work_dir, ignore_errors=True)

    def _recover_interrupted_jobs(self) -> None:
        for job_dir in self.jobs_root.iterdir():
            if JOB_ID_RE.fullmatch(job_dir.name) and not _is_link_like(job_dir) and job_dir.is_dir():
                self._remove_work_dir(job_dir)
        for state_path in self.jobs_root.glob("*/state.json"):
            if _is_link_like(state_path.parent) or _is_link_like(state_path):
                continue
            try:
                state = _load_json(state_path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if state.get("status") not in {"queued", "processing"}:
                continue
            state.update({
                "status": "failed",
                "stage": "interrupted",
                "progress": 100.0,
                "detail": "Training was interrupted because the Desktop application stopped.",
                "completedAt": utc_now(),
                "error": "Training interrupted; create a new run to try again.",
            })
            _write_json_atomic(state_path, state)

    def _active_count(self) -> int:
        self._futures = {
            job_id: future
            for job_id, future in self._futures.items()
            if not future.done()
        }
        return len(self._futures)

    @staticmethod
    def _public(state: dict[str, Any]) -> dict[str, Any]:
        allowed = (
            "schemaVersion", "jobId", "name", "status", "stage", "progress",
            "detail", "createdAt", "startedAt", "completedAt", "error",
            "dataset", "config", "baseArtifactVersion", "candidate",
        )
        return {key: state.get(key) for key in allowed}

    def _merge_progress(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") != "processing":
            return state
        progress_path = self._job_dir(str(state["jobId"])) / "progress.json"
        try:
            progress = _load_json(progress_path)
        except (OSError, ValueError, json.JSONDecodeError):
            return state
        merged = dict(state)
        if isinstance(progress.get("stage"), str):
            merged["stage"] = progress["stage"]
        if isinstance(progress.get("detail"), str):
            merged["detail"] = progress["detail"][:300]
        value = progress.get("progress")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            merged["progress"] = max(0.0, min(99.0, float(value)))
        return merged

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            return self._public(self._merge_progress(self._read_state(job_id)))

    def _list_jobs(self) -> list[dict[str, Any]]:
        states: list[dict[str, Any]] = []
        with self._lock:
            for path in self.jobs_root.glob("*/state.json"):
                if _is_link_like(path.parent) or _is_link_like(path):
                    continue
                try:
                    states.append(self._public(self._merge_progress(_load_json(path))))
                except (OSError, ValueError, json.JSONDecodeError, TrainingServiceError):
                    continue
        states.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
        return states[:MAX_JOBS_RETURNED]

    def summary(self) -> dict[str, Any]:
        dataset_summary = self.dataset_service.summary()
        eligible = [
            item for item in dataset_summary["imports"]
            if item.get("status") == "ready"
            and item.get("labelStatus") == "reviewed"
            and int(item.get("fileCount") or 0) > 0
        ]
        return {
            "schemaVersion": 1,
            "engine": self.health(),
            "eligibleImports": eligible,
            "jobs": self._list_jobs(),
        }

    @staticmethod
    def _clean_import_ids(import_ids: Any) -> list[str]:
        if (
            not isinstance(import_ids, list)
            or not import_ids
            or len(import_ids) > MAX_IMPORTS_PER_JOB
            or any(not isinstance(item, str) for item in import_ids)
        ):
            raise TrainingServiceError(f"Select between 1 and {MAX_IMPORTS_PER_JOB} reviewed dataset batches.", 400)
        return list(dict.fromkeys(import_ids))

    def preview(self, import_ids: Any) -> dict[str, Any]:
        """What a run on these batches would train on, counted once per capture.

        Batches can share captures (a re-exported ring buffer); the snapshot keeps
        each SHA-256 once, so per-batch sums would overstate the selection.
        """
        import_ids = self._clean_import_ids(import_ids)
        try:
            snapshot = self.dataset_service.training_snapshot(import_ids)
        except DatasetServiceError as exc:
            raise TrainingServiceError(str(exc), exc.status) from exc
        capture_bytes = sum(int(item.get("sizeBytes") or 0) for item in snapshot["files"])
        counts = snapshot["counts"]
        return {
            "schemaVersion": 1,
            "importIds": import_ids,
            "fileCount": counts["included"],
            "normalFileCount": counts["normal"],
            "faultFileCount": counts["fault"],
            "excludedFileCount": counts["exclude"],
            "uniqueCaptureCount": counts["total"],
            "captureBytes": capture_bytes,
            "maxCaptureBytes": MAX_TRAINING_CAPTURE_BYTES,
            "withinLimit": capture_bytes <= MAX_TRAINING_CAPTURE_BYTES,
            "hasNormal": counts["normal"] > 0,
        }

    def create_job(
        self,
        *,
        name: str,
        import_ids: list[str],
        epochs: int,
    ) -> dict[str, Any]:
        clean_name = " ".join(name.split()) if isinstance(name, str) else ""
        if not clean_name or len(clean_name) > 120:
            raise TrainingServiceError("Training run name must be between 1 and 120 characters.", 400)
        import_ids = self._clean_import_ids(import_ids)
        if isinstance(epochs, bool) or not isinstance(epochs, int) or not 1 <= epochs <= MAX_EPOCHS:
            raise TrainingServiceError(f"Epochs must be between 1 and {MAX_EPOCHS}.", 400)
        engine = self.health()
        if not engine["available"]:
            raise TrainingServiceError("The PyTorch training engine is unavailable on this PC.", 503)
        with self._lock:
            if self._shutting_down:
                raise TrainingServiceError("The training service is stopping.", 503)
            if self._active_count() >= 1:
                raise TrainingServiceError("Another model training run is already active.", 429)
            try:
                snapshot = self.dataset_service.training_snapshot(import_ids)
            except DatasetServiceError as exc:
                raise TrainingServiceError(str(exc), exc.status) from exc
            if snapshot["counts"]["normal"] <= 0:
                raise TrainingServiceError("At least one Normal capture is required to train the anomaly models.", 422)
            capture_bytes = sum(int(item.get("sizeBytes") or 0) for item in snapshot["files"])
            if capture_bytes > MAX_TRAINING_CAPTURE_BYTES:
                raise TrainingServiceError("The selected training captures exceed the 4 GiB run limit.", 413)

            try:
                base_version = self._base_version()
            except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
                raise TrainingServiceError("The installed base model manifest is invalid.", 503) from exc

            job_id = uuid.uuid4().hex
            job_dir = self._job_dir(job_id, must_exist=False)
            job_dir.mkdir(parents=False, exist_ok=False)
            snapshot_path = job_dir / "snapshot.json"
            _write_json_atomic(snapshot_path, snapshot)
            now = utc_now()
            state = {
                "schemaVersion": 1,
                "jobId": job_id,
                "name": clean_name,
                "status": "queued",
                "stage": "queued",
                "progress": 1.0,
                "detail": "Training run is queued.",
                "createdAt": now,
                "startedAt": None,
                "completedAt": None,
                "error": None,
                "dataset": {
                    "importIds": import_ids,
                    "fileCount": snapshot["counts"]["included"],
                    "normalFileCount": snapshot["counts"]["normal"],
                    "faultFileCount": snapshot["counts"]["fault"],
                    "excludedFileCount": snapshot["counts"]["exclude"],
                },
                "config": {"epochs": epochs, "mode": "safe_fine_tune"},
                "baseArtifactVersion": base_version,
                "candidate": None,
            }
            _write_json_atomic(job_dir / "state.json", state)
            self._futures[job_id] = self._executor.submit(
                self._run_job, job_id, snapshot_path, epochs
            )
            return self._public(state)

    def _verify_candidate(self, job_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
        candidate = result.get("candidate")
        if not isinstance(candidate, dict):
            raise ValueError("worker result has no candidate")
        version = candidate.get("artifactVersion")
        if not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{16}", version):
            raise ValueError("candidate artifact version is invalid")
        manifest = _load_json(job_dir / "candidate" / "manifest.json")
        if manifest.get("artifactVersion") != version:
            raise ValueError("candidate manifest version mismatch")
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise ValueError("candidate manifest files are invalid")
        for name in ("lstm_ae.npz", "gru_fore.npz"):
            metadata = files.get(name)
            path = job_dir / "candidate" / name
            if (
                not isinstance(metadata, dict)
                or not path.is_file()
                or _is_link_like(path)
                or metadata.get("sha256") != _sha256_file(path)
            ):
                raise ValueError(f"candidate artifact failed validation: {name}")
        if candidate.get("approvalStatus") != "manual_validation_required":
            raise ValueError("candidate approval status is invalid")
        training = candidate.get("training")
        if not isinstance(training, dict):
            raise ValueError("candidate training metadata is invalid")
        integer_fields = (
            "epochs", "normalCaptures", "faultReserveCaptures", "normalSessions",
            "faultReserveSessions", "extractedEvents", "aeWindows", "forecasterWindows",
            "aeWindowsAvailable", "forecasterWindowsAvailable", "contributingCaptures",
            "contributingSessions",
        )
        numeric_fields = (
            "aeLossInitial", "aeLossFinal", "forecasterLossInitial",
            "forecasterLossFinal", "durationSeconds",
        )
        if any(
            isinstance(training.get(key), bool)
            or not isinstance(training.get(key), int)
            or int(training[key]) < 0
            for key in integer_fields
        ):
            raise ValueError("candidate training counts are invalid")
        if any(
            isinstance(training.get(key), bool)
            or not isinstance(training.get(key), (int, float))
            or not math.isfinite(float(training[key]))
            or float(training[key]) < 0
            for key in numeric_fields
        ):
            raise ValueError("candidate training metrics are invalid")
        if training.get("device") not in {"cpu", "cuda"}:
            raise ValueError("candidate training device is invalid")
        device_name = training.get("deviceName")
        if not isinstance(device_name, str) or not device_name.strip() or len(device_name) > 200:
            raise ValueError("candidate training device name is invalid")
        return {
            "artifactVersion": version,
            "createdAt": str(manifest.get("createdAt") or candidate.get("createdAt") or ""),
            "approvalStatus": "manual_validation_required",
            "training": training,
            "files": files,
        }

    def _run_job(self, job_id: str, snapshot_path: Path, epochs: int) -> None:
        job_dir = self._job_dir(job_id)
        log_path = job_dir / "training.log"
        result_path = job_dir / "result.json"
        candidate_dir = job_dir / "candidate"
        work_dir = job_dir / "work"
        self._update_state(
            job_id,
            status="processing",
            stage="starting",
            progress=3.0,
            detail="Starting the isolated PyTorch training worker.",
            startedAt=utc_now(),
        )
        engine, _, _ = self._engine_config()
        command = [
            str(engine["python"]),
            str(self.worker_script),
            "--snapshot", str(snapshot_path),
            "--output", str(candidate_dir),
            "--work", str(work_dir),
            "--progress", str(job_dir / "progress.json"),
            "--result", str(result_path),
            "--portable-runtime-dir", str(self.portable_runtime_dir),
            "--ai-project", str(engine["aiProject"]),
            "--baseline-artifacts", str(engine["baselineArtifacts"]),
            "--tshark", str(self.tshark),
            "--epochs", str(epochs),
        ]
        environment = {
            **os.environ,
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "PYTHONHASHSEED": "0",
        }
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            with log_path.open("w", encoding="utf-8", newline="\n") as log:
                process = subprocess.Popen(
                    command,
                    cwd=str(self.worker_script.parent),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    creationflags=creationflags,
                )
                with self._lock:
                    if self._shutting_down:
                        process.terminate()
                        raise TrainingServiceError("Training stopped because the Desktop application is closing.", 503)
                    self._processes[job_id] = process
                try:
                    return_code = process.wait(timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=30)
                    raise TrainingServiceError("Training exceeded the eight-hour safety limit.", 504)
            self._remove_work_dir(job_dir)
            if return_code != 0:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-1200:].strip()
                raise TrainingServiceError(tail or f"Training worker exited with code {return_code}.", 500)
            result = _load_json(result_path)
            if result.get("schemaVersion") != 1:
                raise ValueError("training worker result schema is invalid")
            candidate = self._verify_candidate(job_dir, result)
            self._update_state(
                job_id,
                status="complete",
                stage="complete",
                progress=100.0,
                detail="Candidate model training completed. Manual validation is required before deployment.",
                completedAt=utc_now(),
                error=None,
                candidate=candidate,
            )
        except Exception as exc:
            self._remove_work_dir(job_dir)
            self._update_state(
                job_id,
                status="failed",
                stage="failed",
                progress=100.0,
                detail="Candidate model training failed.",
                completedAt=utc_now(),
                error=str(exc)[:1200],
            )
        finally:
            with self._lock:
                self._processes.pop(job_id, None)
            self._remove_work_dir(job_dir)

    def shutdown(self) -> None:
        """Stop active external workers before the Desktop sidecar exits."""
        with self._lock:
            self._shutting_down = True
            processes = list(self._processes.values())
        for process in processes:
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
        deadline = time.monotonic() + 5.0
        for process in processes:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    pass
        self._executor.shutdown(wait=True, cancel_futures=True)


__all__ = ["ModelTrainingService", "TrainingServiceError"]

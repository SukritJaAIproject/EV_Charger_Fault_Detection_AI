"""Managed PCAP dataset inbox for the desktop retraining workflow.

The installed inference runtime deliberately does not contain PyTorch or the
audited training pipeline.  This service therefore stages immutable, hashed
capture batches and reports the label/training gate explicitly; it never
replaces the production model.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from job_service import CAPTURE_MAGIC


IMPORT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
MAX_CAPTURE_BYTES = 512 * 1024 * 1024
MAX_IMPORT_BYTES = 20 * 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 10_000
# zipfile parses the whole central directory in one go, sized by the end
# record, before any limit can be checked; 10,000 entries with names up to 500
# characters and their extra fields fit well within this bound.
MAX_CENTRAL_DIRECTORY_BYTES = 6 * 1024 * 1024
# Windows refuses os.replace while another process (a scanner, a reader in this
# process) has the target open; such sharing errors clear within moments.
REPLACE_ATTEMPTS = 8
REPLACE_BACKOFF_SECONDS = 0.05
MAX_COMPRESSION_RATIO = 200
# Below this many expanded bytes a high ratio cannot exhaust anything.
RATIO_CHECK_FLOOR_BYTES = 64 * 1024
# CPython bounds the output of DEFLATE reads only; BZIP2/LZMA entries can expand
# to gigabytes in one call before any size check runs. PCAP archives never need them.
ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
# Free space kept beyond the bytes an upload or extraction is about to write.
DISK_RESERVE_BYTES = 512 * 1024 * 1024
# A folder import sends one HTTP request per capture; the manifest is written
# every few files instead of after each one so large folders stay linear.
MANIFEST_FLUSH_FILES = 25
MANIFEST_FLUSH_SECONDS = 2.0
MAX_WARNINGS = 20
MAX_LABEL_HISTORY = 100
INTERRUPTED_REASON = (
    "The import was interrupted before it finished (the app closed or the upload stopped). "
    "Discard it and import the files again."
)
EMPTY_IMPORT_REASON = "No valid PCAP or PCAPNG files were imported."
FAULT_FAMILIES = frozenset({
    "PROTOCOL_FAILED",
    "EVSE_FAULT",
    "ISOLATION_FAULT",
    "EV_ERROR",
    "SESSION_ABORT",
    "SLAC_FAILURE",
    "COMM_FREEZE",
    "NO_POWER_DELIVERED",
})
LABEL_CLASSIFICATIONS = frozenset({"normal", "fault", "exclude"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _next_month_start() -> str:
    now = datetime.now(timezone.utc)
    year = now.year + (1 if now.month == 12 else 0)
    month = 1 if now.month == 12 else now.month + 1
    return datetime(year, month, 1, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_BACKOFF_SECONDS * (attempt + 1))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    _replace_with_retry(temporary, path)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected an object")
    return payload


def _is_link_like(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(info, "st_file_attributes", 0) & reparse)


def _normalise_relative_path(value: str) -> str:
    candidate = value.replace("\\", "/").strip()
    if not candidate or "\x00" in candidate or len(candidate) > 500:
        raise DatasetServiceError("Invalid dataset relative path.", 400)
    path = PurePosixPath(candidate)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DatasetServiceError("Dataset paths must remain inside the selected folder.", 400)
    if ":" in path.parts[0]:
        raise DatasetServiceError("Drive-qualified dataset paths are not allowed.", 400)
    return path.as_posix()


def _central_directory_bounds(path: Path) -> tuple[int, int]:
    """Entry count and central-directory size exactly as zipfile will read them.

    zipfile.ZipFile() reads the whole central directory and builds an object per
    record before infolist() returns, so a crafted archive with a million
    records costs gigabytes of memory before any limit could be checked. The
    size it parses comes from the end record, replaced by a ZIP64 record found
    directly before it whenever one is there, whatever the plain record says.
    Calling zipfile's own end-record reader keeps this check and the parser in
    agreement; a separate implementation could be fed a different answer.
    """
    with path.open("rb") as handle:
        endrec = zipfile._EndRecData(handle)  # noqa: SLF001 - see the docstring
    if not endrec:
        raise zipfile.BadZipFile("end of central directory not found")
    return int(endrec[zipfile._ECD_ENTRIES_TOTAL]), int(endrec[zipfile._ECD_SIZE])  # noqa: SLF001


def _ensure_free_space(directory: Path, needed_bytes: int) -> None:
    free = shutil.disk_usage(directory).free
    if free < needed_bytes + DISK_RESERVE_BYTES:
        raise DatasetServiceError(
            "There is not enough free disk space for this dataset import.",
            507,
        )


def _capture_extension(name: str) -> str | None:
    suffix = Path(name).suffix.lower()
    return suffix if suffix in {".pcap", ".pcapng"} else None


class DatasetServiceError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class DatasetUpload:
    import_id: str
    filename: str
    relative_path: str
    source_type: str
    expected_bytes: int
    temp_path: Path
    handle: BinaryIO
    received_bytes: int = 0
    closed: bool = False


class TrainingDatasetService:
    """Persist capture batches under a content-addressed, app-owned directory.

    Locking: ``_lock`` guards the shared indexes (known content hashes, the
    manifest/label caches and the published state of open imports) and is only
    held for short sections. Each import has its own lock that serialises its
    uploads, so a long ZIP ingest never blocks labelling or the summary.
    """

    def __init__(self, root: Path):
        self.root = root
        self.imports_root = root / "imports"
        self.files_root = root / "files"
        self.labels_root = root / "labels"
        self.root.mkdir(parents=True, exist_ok=True)
        self.imports_root.mkdir(parents=True, exist_ok=True)
        self.files_root.mkdir(parents=True, exist_ok=True)
        self.labels_root.mkdir(parents=True, exist_ok=True)
        if any(_is_link_like(path) for path in (self.root, self.imports_root, self.files_root, self.labels_root)):
            raise DatasetServiceError("Dataset storage cannot use links or junctions.", 500)
        self._lock = threading.RLock()
        self._label_write_lock = threading.Lock()
        self._import_locks: dict[str, threading.Lock] = {}
        # uploading imports: full state, private to the import's lock
        self._open_states: dict[str, dict[str, Any]] = {}
        self._open_digests: dict[str, set[str]] = {}
        self._unflushed: dict[str, tuple[int, float]] = {}
        # published copy of an open import's public fields (no file list)
        self._open_public: dict[str, dict[str, Any]] = {}
        # import_id -> (mtime_ns, size, state, digest set) for finished manifests
        self._manifest_cache: dict[str, tuple[int, int, dict[str, Any], frozenset[str]]] = {}
        # digest -> ("missing" | "ok" | "invalid", record)
        self._label_cache: dict[str, tuple[str, dict[str, Any] | None]] = {}
        self._recover_imports()
        self._known_hashes, complete = self._read_known_hashes()
        # Only with every manifest read can a stored capture be called unreferenced:
        # a manifest locked by a scanner or damaged must never cost its captures.
        if complete:
            self._collect_unreferenced_content()

    # ------------------------------------------------------------------ storage

    def _import_dirs(self) -> list[Path]:
        found = []
        for candidate in self.imports_root.iterdir():
            try:
                if IMPORT_ID_RE.fullmatch(candidate.name) and not _is_link_like(candidate) and candidate.is_dir():
                    found.append(candidate)
            except OSError:
                continue
        return found

    def _recover_imports(self) -> None:
        """Nothing can be uploading when the sidecar starts: finish what a crash left."""
        for leftover in self.imports_root.glob(".discarded-*"):
            if not _is_link_like(leftover) and leftover.is_dir():
                shutil.rmtree(leftover, ignore_errors=True)
        for import_dir in self._import_dirs():
            for leftover in list(import_dir.glob(".upload-*.tmp")) + list(import_dir.glob(".capture-*.tmp")):
                try:
                    if not _is_link_like(leftover):
                        leftover.unlink(missing_ok=True)
                except OSError:
                    continue
            manifest = import_dir / "manifest.json"
            try:
                state = _load_json(manifest)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if state.get("status") == "uploading":
                state["status"] = "failed"
                state["failureReason"] = INTERRUPTED_REASON
                state["completedAt"] = utc_now()
                try:
                    _write_json_atomic(manifest, state)
                except OSError:
                    continue

    def _read_known_hashes(self, skip: frozenset[str] = frozenset()) -> tuple[set[str], bool]:
        """Captures referenced by the manifests on disk, and whether every one was read.

        An import directory without a manifest was never written past creation
        and references nothing; any other read failure makes the view partial.
        """
        known: set[str] = set()
        complete = True
        for import_dir in self._import_dirs():
            if import_dir.name in skip:
                continue
            try:
                payload = _load_json(import_dir / "manifest.json")
            except FileNotFoundError:
                continue
            except (OSError, ValueError, json.JSONDecodeError):
                complete = False
                continue
            for item in payload.get("files") or []:
                digest = item.get("sha256") if isinstance(item, dict) else None
                if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
                    known.add(digest)
        return known, complete

    def _content_path(self, digest: str, capture_format: str) -> Path:
        extension = ".pcapng" if capture_format == "pcapng" else ".pcap"
        return self.files_root / digest[:2] / f"{digest}{extension}"

    def _stored_content(self, candidates: set[str] | None) -> list[Path]:
        if candidates is not None:
            return [self._content_path(digest, fmt) for digest in candidates for fmt in ("pcap", "pcapng")]
        blobs: list[Path] = []
        for prefix_dir in self.files_root.iterdir():
            try:
                if not _is_link_like(prefix_dir) and prefix_dir.is_dir():
                    blobs.extend(prefix_dir.iterdir())
            except OSError:
                continue
        return blobs

    def _collect_unreferenced_content(self, candidates: set[str] | None = None) -> int:
        """Remove stored captures that no manifest references (left by a crash or a discard).

        Runs under the shared lock: an upload elsewhere may be about to reuse a blob.
        """
        removed = 0
        with self._lock:
            referenced = set(self._known_hashes)
            for digests in self._open_digests.values():
                referenced |= digests
            for blob in self._stored_content(candidates):
                digest = blob.name.split(".", 1)[0]
                if digest in referenced or not SHA256_RE.fullmatch(digest):
                    continue
                try:
                    if _is_link_like(blob) or not blob.is_file():
                        continue
                    blob.unlink()
                    removed += 1
                except OSError:
                    continue
        return removed

    def _import_lock(self, import_id: str) -> threading.Lock:
        with self._lock:
            lock = self._import_locks.get(import_id)
            if lock is None:
                lock = self._import_locks[import_id] = threading.Lock()
            return lock

    def _import_dir(self, import_id: str, *, must_exist: bool = True) -> Path:
        if not isinstance(import_id, str) or not IMPORT_ID_RE.fullmatch(import_id):
            raise DatasetServiceError("Invalid dataset import id.", 400)
        candidate = self.imports_root / import_id
        if candidate.exists() and _is_link_like(candidate):
            raise DatasetServiceError("Dataset import storage is unsafe.", 409)
        if must_exist and not candidate.is_dir():
            raise DatasetServiceError("Dataset import not found.", 404)
        return candidate

    def _state_path(self, import_id: str) -> Path:
        return self._import_dir(import_id) / "manifest.json"

    def _read_state(self, import_id: str) -> dict[str, Any]:
        """The current state of one import: in-memory while uploading, else the manifest."""
        with self._lock:
            open_state = self._open_states.get(import_id)
        if open_state is not None:
            return open_state
        path = self._state_path(import_id)
        try:
            info = path.stat()
        except FileNotFoundError as exc:
            raise DatasetServiceError("Dataset import not found.", 404) from exc
        except OSError as exc:
            raise DatasetServiceError("Dataset import state is unavailable.", 503) from exc
        with self._lock:
            cached = self._manifest_cache.get(import_id)
            if cached and cached[0] == info.st_mtime_ns and cached[1] == info.st_size:
                return cached[2]
        try:
            state = _load_json(path)
        except FileNotFoundError as exc:
            raise DatasetServiceError("Dataset import not found.", 404) from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise DatasetServiceError("Dataset import state is unavailable.", 503) from exc
        digests = frozenset(
            item["sha256"] for item in state.get("files") or []
            if isinstance(item, dict) and isinstance(item.get("sha256"), str) and SHA256_RE.fullmatch(item["sha256"])
        )
        with self._lock:
            self._manifest_cache[import_id] = (info.st_mtime_ns, info.st_size, state, digests)
        return state

    def _write_state(self, import_id: str, state: dict[str, Any]) -> None:
        path = self._state_path(import_id)
        _write_json_atomic(path, state)
        with self._lock:
            self._manifest_cache.pop(import_id, None)
            self._unflushed[import_id] = (0, time.monotonic())

    def _maybe_flush(self, import_id: str, state: dict[str, Any], *, force: bool = False) -> None:
        with self._lock:
            pending, since = self._unflushed.get(import_id, (0, time.monotonic()))
            pending += 1
            self._unflushed[import_id] = (pending, since)
        if force or pending >= MANIFEST_FLUSH_FILES or time.monotonic() - since >= MANIFEST_FLUSH_SECONDS:
            self._write_state(import_id, state)

    def _publish_open(self, import_id: str, state: dict[str, Any]) -> None:
        public = self._public(state, with_labels=False)
        with self._lock:
            if import_id in self._open_states:
                self._open_public[import_id] = public

    def _open(self, import_id: str) -> dict[str, Any]:
        """Load an uploading import into memory; caller holds its import lock."""
        with self._lock:
            state = self._open_states.get(import_id)
        if state is not None:
            return state
        state = self._read_state(import_id)
        if state.get("status") != "uploading":
            raise DatasetServiceError("This dataset import is already finalised.", 409)
        state = json.loads(json.dumps(state))  # private, mutable copy
        digests = {
            item["sha256"] for item in state.get("files") or []
            if isinstance(item, dict) and isinstance(item.get("sha256"), str)
        }
        with self._lock:
            self._open_states[import_id] = state
            self._open_digests[import_id] = digests
        self._publish_open(import_id, state)
        return state

    def _close(self, import_id: str) -> None:
        with self._lock:
            self._open_states.pop(import_id, None)
            self._open_digests.pop(import_id, None)
            self._open_public.pop(import_id, None)
            self._unflushed.pop(import_id, None)

    # ------------------------------------------------------------------- labels

    def _label_path(self, digest: str, *, create_parent: bool = False) -> Path:
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise DatasetServiceError("Invalid capture SHA-256.", 400)
        parent = self.labels_root / digest[:2]
        if create_parent:
            parent.mkdir(parents=True, exist_ok=True)
        if parent.exists() and _is_link_like(parent):
            raise DatasetServiceError("Ground-truth label storage is unsafe.", 409)
        target = parent / f"{digest}.json"
        if target.exists() and _is_link_like(target):
            raise DatasetServiceError("Ground-truth label file is unsafe.", 409)
        return target

    def _label_entry(self, digest: str) -> tuple[str, dict[str, Any] | None]:
        """("missing" | "ok" | "invalid", record). Labels are written only by this
        service, so a per-process cache stays consistent with the files."""
        with self._lock:
            cached = self._label_cache.get(digest)
        if cached is not None:
            return cached
        try:
            path = self._label_path(digest)
            payload = _load_json(path)
            current = payload.get("current")
            if (
                payload.get("schemaVersion") != 1
                or payload.get("sha256") != digest
                or not isinstance(payload.get("history"), list)
                or not isinstance(current, dict)
            ):
                raise ValueError("label payload is invalid")
            entry: tuple[str, dict[str, Any] | None] = ("ok", self._validate_label_record(current))
        except FileNotFoundError:
            entry = ("missing", None)
        except (OSError, ValueError, json.JSONDecodeError, DatasetServiceError):
            # unreadable or invalid: shown as needing review, never fatal
            entry = ("invalid", None)
        with self._lock:
            self._label_cache[digest] = entry
        return entry

    def _read_label(self, digest: str) -> dict[str, Any] | None:
        return self._label_entry(digest)[1]

    @staticmethod
    def _validate_label_record(current: dict[str, Any]) -> dict[str, Any]:
        classification = current.get("classification")
        fault_family = current.get("faultFamily")
        reviewer = current.get("reviewer")
        notes = current.get("notes")
        revision = current.get("revision")
        if (
            classification not in LABEL_CLASSIFICATIONS
            or not isinstance(reviewer, str)
            or not reviewer.strip()
            or len(reviewer) > 80
            or not isinstance(notes, str)
            or len(notes) > 2_000
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or not isinstance(current.get("createdAt"), str)
            or not current["createdAt"]
            or not isinstance(current.get("updatedAt"), str)
            or not current["updatedAt"]
        ):
            raise DatasetServiceError("Ground-truth label data is invalid.", 503)
        if classification == "fault":
            if fault_family not in FAULT_FAMILIES:
                raise DatasetServiceError("Ground-truth label data is invalid.", 503)
        elif fault_family is not None:
            raise DatasetServiceError("Ground-truth label data is invalid.", 503)
        return current

    def _label_progress(self, state: dict[str, Any]) -> dict[str, Any]:
        total = labeled = normal = fault = excluded = invalid = 0
        for item in state.get("files") or []:
            if not isinstance(item, dict):
                continue
            digest = item.get("sha256")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                continue
            total += 1
            status, label = self._label_entry(digest)
            if status == "invalid":
                invalid += 1
                continue
            if label is None:
                continue
            labeled += 1
            classification = label.get("classification")
            if classification == "normal":
                normal += 1
            elif classification == "fault":
                fault += 1
            elif classification == "exclude":
                excluded += 1
        label_status = "unlabeled" if labeled == 0 else "reviewed" if total > 0 and labeled == total else "partially_labeled"
        return {
            "labelStatus": label_status,
            "labeledFileCount": labeled,
            "remainingFileCount": max(0, total - labeled),
            "normalFileCount": normal,
            "faultFileCount": fault,
            "excludedFileCount": excluded,
            "invalidLabelCount": invalid,
        }

    def _public(self, state: dict[str, Any], *, with_labels: bool = True) -> dict[str, Any]:
        keys = (
            "schemaVersion", "importId", "name", "sourceType", "status",
            "createdAt", "completedAt", "fileCount", "bytes",
            "duplicateCount", "rejectedCount", "recommendedRetrainAt",
        )
        public = {key: state.get(key) for key in keys}
        public["failureReason"] = state.get("failureReason")
        if with_labels and state.get("status") == "ready":
            public.update(self._label_progress(state))
        else:
            public.update({
                "labelStatus": "unlabeled",
                "labeledFileCount": 0,
                "remainingFileCount": int(state.get("fileCount") or 0),
                "normalFileCount": 0,
                "faultFileCount": 0,
                "excludedFileCount": 0,
                "invalidLabelCount": 0,
            })
        public["readyForRetrain"] = False
        public["warnings"] = list(state.get("warnings") or [])[-MAX_WARNINGS:]
        return public

    # ------------------------------------------------------------------ imports

    def create_import(self, name: str, source_type: str) -> dict[str, Any]:
        clean_name = " ".join(str(name).split())
        if not clean_name or len(clean_name) > 120:
            raise DatasetServiceError("Dataset name must be between 1 and 120 characters.", 400)
        if source_type not in {"zip", "folder"}:
            raise DatasetServiceError("Dataset sourceType must be zip or folder.", 400)
        import_id = uuid.uuid4().hex
        import_dir = self._import_dir(import_id, must_exist=False)
        import_dir.mkdir(parents=False, exist_ok=False)
        state: dict[str, Any] = {
            "schemaVersion": 1,
            "importId": import_id,
            "name": clean_name,
            "sourceType": source_type,
            "status": "uploading",
            "createdAt": utc_now(),
            "completedAt": None,
            "failureReason": None,
            "fileCount": 0,
            "bytes": 0,
            "duplicateCount": 0,
            "rejectedCount": 0,
            "labelStatus": "unlabeled",
            "readyForRetrain": False,
            "recommendedRetrainAt": _next_month_start(),
            "warnings": [],
            "files": [],
        }
        _write_json_atomic(import_dir / "manifest.json", state)
        return self._public(state, with_labels=False)

    def begin_upload(
        self,
        import_id: str,
        filename: str,
        relative_path: str,
        *,
        content_length: int,
    ) -> DatasetUpload:
        if content_length <= 0 or content_length > MAX_UPLOAD_BYTES:
            raise DatasetServiceError("Dataset upload is empty or exceeds 4 GiB.", 413)
        clean_filename = Path(filename).name
        if clean_filename != filename or not clean_filename or len(clean_filename) > 255:
            raise DatasetServiceError("Invalid dataset filename.", 400)
        clean_relative = _normalise_relative_path(relative_path or clean_filename)
        state = self._read_state(import_id)
        if state.get("status") != "uploading":
            raise DatasetServiceError("This dataset import is already finalised.", 409)
        source_type = str(state.get("sourceType"))
        extension = Path(clean_filename).suffix.lower()
        if source_type == "zip" and extension != ".zip":
            raise DatasetServiceError("ZIP imports accept one .zip archive.", 415)
        if source_type == "folder" and _capture_extension(clean_filename) is None:
            raise DatasetServiceError("Folder imports accept only .pcap and .pcapng files.", 415)
        import_dir = self._import_dir(import_id)
        # the upload temp file, plus room to move or extract it into storage
        _ensure_free_space(import_dir, content_length * 2)
        temp_path = import_dir / f".upload-{uuid.uuid4().hex}.tmp"
        return DatasetUpload(
            import_id=import_id,
            filename=clean_filename,
            relative_path=clean_relative,
            source_type=source_type,
            expected_bytes=content_length,
            temp_path=temp_path,
            handle=temp_path.open("xb"),
        )

    @staticmethod
    def write_upload(upload: DatasetUpload, chunk: bytes) -> None:
        if upload.closed:
            raise DatasetServiceError("Dataset upload is already closed.", 409)
        if upload.received_bytes + len(chunk) > upload.expected_bytes:
            raise DatasetServiceError("Dataset upload exceeded Content-Length.", 400)
        upload.handle.write(chunk)
        upload.received_bytes += len(chunk)

    @staticmethod
    def abort_upload(upload: DatasetUpload) -> None:
        if not upload.closed:
            upload.handle.close()
            upload.closed = True
        upload.temp_path.unlink(missing_ok=True)

    @staticmethod
    def _warning(state: dict[str, Any], message: str) -> None:
        warnings = state.setdefault("warnings", [])
        warnings.append(message[:300])
        if len(warnings) > MAX_WARNINGS:
            del warnings[:-MAX_WARNINGS]

    def _accept_temp_capture(
        self,
        state: dict[str, Any],
        temp_path: Path,
        *,
        original_name: str,
        relative_path: str,
        size_bytes: int,
        digest: str,
        capture_format: str,
    ) -> None:
        import_id = str(state["importId"])
        if state["bytes"] + size_bytes > MAX_IMPORT_BYTES:
            temp_path.unlink(missing_ok=True)
            raise DatasetServiceError("Dataset import exceeds 20 GiB.", 413)
        with self._lock:
            in_this_import = digest in self._open_digests.get(import_id, set())
        if in_this_import:
            state["duplicateCount"] += 1
            temp_path.unlink(missing_ok=True)
            return
        target = self._content_path(digest, capture_format)
        target_dir = target.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        if _is_link_like(target_dir):
            temp_path.unlink(missing_ok=True)
            raise DatasetServiceError("Dataset content storage is unsafe.", 409)
        if target.exists() and _is_link_like(target):
            temp_path.unlink(missing_ok=True)
            raise DatasetServiceError("Dataset content file is unsafe.", 409)
        with self._lock:
            content_reused = digest in self._known_hashes and target.is_file()
            if content_reused:
                temp_path.unlink(missing_ok=True)
            else:
                os.replace(temp_path, target)
            self._known_hashes.add(digest)
            self._open_digests.setdefault(import_id, set()).add(digest)
        if content_reused:
            state["duplicateCount"] += 1
        state["files"].append({
            "originalName": original_name,
            "relativePath": relative_path,
            "sizeBytes": size_bytes,
            "sha256": digest,
            "captureFormat": capture_format,
            "contentReused": content_reused,
        })
        state["fileCount"] += 1
        state["bytes"] += size_bytes

    def _stream_capture(
        self,
        state: dict[str, Any],
        source: BinaryIO,
        *,
        original_name: str,
        relative_path: str,
        declared_size: int | None = None,
    ) -> None:
        extension = _capture_extension(original_name)
        if extension is None:
            raise DatasetServiceError("Only .pcap and .pcapng captures are accepted.", 415)
        temporary = self._import_dir(str(state["importId"])) / f".capture-{uuid.uuid4().hex}.tmp"
        digest = sha256()
        size = 0
        prefix = b""
        try:
            with temporary.open("xb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_CAPTURE_BYTES:
                        raise DatasetServiceError("A capture exceeds 512 MiB.", 413)
                    if len(prefix) < 4:
                        prefix = (prefix + chunk)[:4]
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            magic = CAPTURE_MAGIC.get(prefix)
            if not magic or size < magic[1]:
                raise DatasetServiceError("A selected file is not a valid PCAP or PCAPNG capture.", 415)
            if declared_size is not None and size != declared_size:
                raise DatasetServiceError("Archive entry size changed while it was read.", 400)
            self._accept_temp_capture(
                state,
                temporary,
                original_name=original_name,
                relative_path=relative_path,
                size_bytes=size,
                digest=digest.hexdigest(),
                capture_format=magic[0],
            )
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _ingest_direct(self, state: dict[str, Any], upload: DatasetUpload) -> None:
        try:
            with upload.temp_path.open("rb") as source:
                self._stream_capture(
                    state,
                    source,
                    original_name=upload.filename,
                    relative_path=upload.relative_path,
                    declared_size=upload.expected_bytes,
                )
        finally:
            upload.temp_path.unlink(missing_ok=True)

    def _ingest_zip(self, state: dict[str, Any], upload: DatasetUpload) -> None:
        import_id = str(state["importId"])
        ignored = 0
        try:
            entries_declared, cd_size = _central_directory_bounds(upload.temp_path)
            if entries_declared > MAX_ARCHIVE_ENTRIES:
                raise DatasetServiceError("ZIP archive contains more than 10,000 entries.", 413)
            if cd_size > MAX_CENTRAL_DIRECTORY_BYTES:
                raise DatasetServiceError("ZIP archive directory is too large.", 413)
            with zipfile.ZipFile(upload.temp_path) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ARCHIVE_ENTRIES:
                    raise DatasetServiceError("ZIP archive contains more than 10,000 entries.", 413)
                total_declared = sum(max(0, item.file_size) for item in entries if not item.is_dir())
                if total_declared > MAX_IMPORT_BYTES:
                    raise DatasetServiceError("ZIP archive expands beyond 20 GiB.", 413)
                _ensure_free_space(self._import_dir(import_id), min(total_declared, MAX_IMPORT_BYTES))
                for item in entries:
                    if item.is_dir():
                        continue
                    try:
                        relative_path = _normalise_relative_path(item.filename)
                    except DatasetServiceError as exc:
                        state["rejectedCount"] += 1
                        self._warning(state, f"Rejected unsafe ZIP path: {exc}")
                        continue
                    if _capture_extension(relative_path) is None:
                        ignored += 1
                        continue
                    unix_mode = (item.external_attr >> 16) & 0o170000
                    compressed = max(1, item.compress_size)
                    if item.flag_bits & 0x1 or unix_mode == stat.S_IFLNK:
                        state["rejectedCount"] += 1
                        self._warning(state, f"Rejected encrypted or linked entry: {relative_path}")
                        continue
                    if item.compress_type not in ALLOWED_COMPRESSION:
                        state["rejectedCount"] += 1
                        self._warning(state, f"Rejected unsupported compression method: {relative_path}")
                        continue
                    if item.file_size <= 0 or item.file_size > MAX_CAPTURE_BYTES:
                        state["rejectedCount"] += 1
                        self._warning(state, f"Rejected invalid capture size: {relative_path}")
                        continue
                    if item.file_size > RATIO_CHECK_FLOOR_BYTES and item.file_size / compressed > MAX_COMPRESSION_RATIO:
                        state["rejectedCount"] += 1
                        self._warning(state, f"Rejected suspicious compression ratio: {relative_path}")
                        continue
                    try:
                        with archive.open(item, "r") as source:
                            self._stream_capture(
                                state,
                                source,
                                original_name=PurePosixPath(relative_path).name,
                                relative_path=relative_path,
                                declared_size=item.file_size,
                            )
                    except MemoryError:
                        raise
                    except Exception as exc:  # damaged data, CRC errors, disk errors: skip the entry
                        state["rejectedCount"] += 1
                        self._warning(state, f"Rejected {relative_path}: {exc}")
                    self._publish_open(import_id, state)
                if ignored:
                    self._warning(state, f"Ignored {ignored} non-PCAP file(s) in the ZIP archive.")
        except zipfile.BadZipFile as exc:
            raise DatasetServiceError("The selected ZIP archive is invalid.", 415) from exc
        finally:
            upload.temp_path.unlink(missing_ok=True)

    def finish_upload(self, upload: DatasetUpload) -> dict[str, Any]:
        if upload.closed:
            raise DatasetServiceError("Dataset upload is already closed.", 409)
        try:
            upload.handle.flush()
            os.fsync(upload.handle.fileno())
        finally:
            upload.handle.close()
            upload.closed = True
        if upload.received_bytes != upload.expected_bytes:
            upload.temp_path.unlink(missing_ok=True)
            raise DatasetServiceError("The upload ended before Content-Length.", 400)
        with self._import_lock(upload.import_id):
            try:
                state = self._open(upload.import_id)
            except BaseException:
                upload.temp_path.unlink(missing_ok=True)
                raise
            try:
                if upload.source_type == "zip":
                    self._ingest_zip(state, upload)
                else:
                    self._ingest_direct(state, upload)
            except MemoryError:
                raise
            except Exception as exc:  # recorded on the batch; the upload itself was received
                state["rejectedCount"] += 1
                message = str(exc) if isinstance(exc, DatasetServiceError) else f"Rejected {upload.filename}: {exc}"
                self._warning(state, message)
            finally:
                upload.temp_path.unlink(missing_ok=True)
                # A ZIP is one request: always try to record what it brought in. The
                # capture itself is stored and held in memory, so a failed manifest
                # write is retried by the next flush or by completion, not reported
                # as a failed upload.
                try:
                    self._maybe_flush(upload.import_id, state, force=upload.source_type == "zip")
                except OSError:
                    pass
                self._publish_open(upload.import_id, state)
            return self._public(state, with_labels=False)

    def complete_import(self, import_id: str) -> dict[str, Any]:
        with self._import_lock(import_id):
            state = self._read_state(import_id)
            if state.get("status") != "uploading":
                return self._public(state)
            state = self._open(import_id)
            # Build the final state aside and keep the open one untouched until the
            # manifest is written: a failed write leaves the batch uploading and the
            # request can simply be retried.
            final = dict(state)
            final["completedAt"] = utc_now()
            if int(state.get("fileCount") or 0) <= 0:
                final["status"] = "failed"
                final["failureReason"] = EMPTY_IMPORT_REASON
                self._write_state(import_id, final)
                self._close(import_id)
                raise DatasetServiceError(EMPTY_IMPORT_REASON, 422)
            final["status"] = "ready"
            self._write_state(import_id, final)
            self._close(import_id)
            return self._public(final)

    def discard_import(self, import_id: str) -> dict[str, Any]:
        """Delete an import that never became ready, and captures only it referenced.

        Ready batches are reviewed ground truth and cannot be discarded here.
        Labels stay: they are keyed by content and are reused if the capture returns.
        """
        with self._import_lock(import_id):
            state = self._read_state(import_id)
            if state.get("status") == "ready":
                raise DatasetServiceError("A completed dataset batch cannot be discarded.", 409)
            import_dir = self._import_dir(import_id)
            own = {
                item["sha256"] for item in state.get("files") or []
                if isinstance(item, dict) and isinstance(item.get("sha256"), str) and SHA256_RE.fullmatch(item["sha256"])
            }
            # Rename first: it fails as a unit while a file upload into this batch
            # still has its temp file open, and the batch then stays intact.
            trash = self.imports_root / f".discarded-{import_id}-{uuid.uuid4().hex[:8]}"
            try:
                _replace_with_retry(import_dir, trash)
            except OSError as exc:
                raise DatasetServiceError(
                    "This dataset batch is busy: a file is still uploading or another program has it open. "
                    "Try again in a moment.",
                    409,
                ) from exc
            with self._lock:
                own |= self._open_digests.get(import_id, set())
            self._close(import_id)
            shutil.rmtree(trash, ignore_errors=True)
            with self._lock:
                self._manifest_cache.pop(import_id, None)
                self._import_locks.pop(import_id, None)
                # open imports are known from memory; their manifests are being flushed
                known, complete = self._read_known_hashes(frozenset(self._open_states))
                for digests in self._open_digests.values():
                    known |= digests
                self._known_hashes = known
            removed = self._collect_unreferenced_content(own) if complete else 0
            return {"schemaVersion": 1, "importId": import_id, "discarded": True, "removedContentFiles": removed}

    # ------------------------------------------------------------------- review

    def label_batch(self, import_id: str) -> dict[str, Any]:
        state = self._read_state(import_id)
        if state.get("status") != "ready":
            raise DatasetServiceError("Only completed dataset batches can be labelled.", 409)
        files: list[dict[str, Any]] = []
        for item in state.get("files") or []:
            if not isinstance(item, dict):
                continue
            digest = item.get("sha256")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                continue
            label_status, label = self._label_entry(digest)
            files.append({
                "sha256": digest,
                "originalName": str(item.get("originalName") or "capture.pcap"),
                "relativePath": str(item.get("relativePath") or item.get("originalName") or "capture.pcap"),
                "sizeBytes": int(item.get("sizeBytes") or 0),
                "captureFormat": str(item.get("captureFormat") or "pcap"),
                "label": label,
                "labelInvalid": label_status == "invalid",
            })
        progress = self._label_progress(state)
        return {
            "schemaVersion": 1,
            "importId": state["importId"],
            "name": state["name"],
            "status": state["status"],
            "fileCount": len(files),
            **progress,
            "files": files,
        }

    def save_label(
        self,
        import_id: str,
        *,
        digest: str,
        classification: str,
        fault_family: str | None,
        reviewer: str,
        notes: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise DatasetServiceError("Invalid capture SHA-256.", 400)
        if not isinstance(classification, str) or classification not in LABEL_CLASSIFICATIONS:
            raise DatasetServiceError("Classification must be normal, fault, or exclude.", 400)
        if not isinstance(reviewer, str):
            raise DatasetServiceError("Reviewer name must be text.", 400)
        if not isinstance(notes, str):
            raise DatasetServiceError("Ground-truth notes must be text.", 400)
        if fault_family is not None and not isinstance(fault_family, str):
            raise DatasetServiceError("Fault family must be text or null.", 400)
        clean_reviewer = " ".join(reviewer.split())
        if not clean_reviewer or len(clean_reviewer) > 80:
            raise DatasetServiceError("Reviewer name must be between 1 and 80 characters.", 400)
        clean_notes = notes.strip()
        if len(clean_notes) > 2_000:
            raise DatasetServiceError("Ground-truth notes cannot exceed 2,000 characters.", 400)
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise DatasetServiceError("expectedRevision must be a non-negative integer.", 400)
        normalized_family = str(fault_family or "").strip().upper() or None
        if classification == "fault":
            if normalized_family not in FAULT_FAMILIES:
                raise DatasetServiceError("A supported fault family is required for a fault label.", 400)
        elif normalized_family is not None:
            raise DatasetServiceError("Fault family is only valid for a fault label.", 400)

        state = self._read_state(import_id)
        if state.get("status") != "ready":
            raise DatasetServiceError("Only completed dataset batches can be labelled.", 409)
        with self._lock:
            cached = self._manifest_cache.get(import_id)
            members = cached[3] if cached else None
        if members is None:
            members = frozenset(
                item.get("sha256") for item in state.get("files") or [] if isinstance(item, dict)
            )
        if digest not in members:
            raise DatasetServiceError("Capture is not part of this dataset batch.", 404)

        with self._label_write_lock:
            path = self._label_path(digest, create_parent=True)
            unreadable = False
            try:
                payload = _load_json(path)
                current = payload.get("current")
                if (
                    payload.get("schemaVersion") != 1
                    or payload.get("sha256") != digest
                    or not isinstance(payload.get("history"), list)
                    or (current is not None and not isinstance(current, dict))
                ):
                    raise ValueError("label payload is invalid")
                if current is not None:
                    current = self._validate_label_record(current)
            except FileNotFoundError:
                payload = {"schemaVersion": 1, "sha256": digest, "current": None, "history": []}
                current = None
            except (OSError, ValueError, json.JSONDecodeError, DatasetServiceError):
                unreadable = True
                payload = {"schemaVersion": 1, "sha256": digest, "current": None, "history": []}
                current = None
            current_revision = current["revision"] if current else 0
            if current_revision != expected_revision:
                raise DatasetServiceError(
                    "This label changed in another window. Refresh before saving again.",
                    409,
                )
            if unreadable:
                # keep the unreadable file for inspection and start a fresh record
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                try:
                    os.replace(path, path.with_name(f"{digest}.invalid-{stamp}.json"))
                except OSError as exc:
                    raise DatasetServiceError("Ground-truth label data is unavailable.", 503) from exc

            timestamp = utc_now()
            if current:
                history = payload.get("history")
                if not isinstance(history, list):
                    history = []
                history.append(current)
                payload["history"] = history[-MAX_LABEL_HISTORY:]
            else:
                payload["history"] = []
            label = {
                "classification": classification,
                "faultFamily": normalized_family,
                "reviewer": clean_reviewer,
                "notes": clean_notes,
                "revision": current_revision + 1,
                "createdAt": current.get("createdAt") if current else timestamp,
                "updatedAt": timestamp,
            }
            payload.update({"schemaVersion": 1, "sha256": digest, "current": label})
            _write_json_atomic(path, payload)
            with self._lock:
                self._label_cache[digest] = ("ok", label)
            return label

    def training_snapshot(self, import_ids: list[str]) -> dict[str, Any]:
        """Freeze reviewed labels and trusted content paths for one training run.

        The snapshot is internal to the Desktop runtime and is never returned
        by an HTTP endpoint because it contains absolute app-owned file paths.
        Duplicate capture hashes across selected batches are included once.
        """
        if (
            not isinstance(import_ids, list)
            or not import_ids
            or any(not isinstance(item, str) for item in import_ids)
        ):
            raise DatasetServiceError("Select at least one reviewed dataset batch.", 400)
        unique_ids = list(dict.fromkeys(import_ids))
        files: list[dict[str, Any]] = []
        seen: set[str] = set()
        counts = {"total": 0, "included": 0, "normal": 0, "fault": 0, "exclude": 0}
        source_imports: list[dict[str, str]] = []
        for import_id in unique_ids:
            state = self._read_state(import_id)
            if state.get("status") != "ready":
                raise DatasetServiceError("Only completed dataset batches can be trained.", 409)
            progress = self._label_progress(state)
            if progress["labelStatus"] != "reviewed":
                raise DatasetServiceError("Every capture in a training batch must have a reviewed label.", 409)
            source_imports.append({"importId": import_id, "name": str(state.get("name") or import_id)})
            for item in state.get("files") or []:
                if not isinstance(item, dict):
                    continue
                digest = item.get("sha256")
                if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest) or digest in seen:
                    continue
                label = self._read_label(digest)
                if label is None:
                    raise DatasetServiceError("A reviewed capture label is unavailable.", 503)
                capture_format = str(item.get("captureFormat") or "")
                content_path = self._content_path(digest, capture_format)
                if not content_path.is_file() or _is_link_like(content_path):
                    raise DatasetServiceError("A training capture is missing or unsafe.", 503)
                expected_size = item.get("sizeBytes")
                if not isinstance(expected_size, int) or expected_size < 0 or content_path.stat().st_size != expected_size:
                    raise DatasetServiceError("A training capture failed its size check.", 503)
                classification = str(label["classification"])
                counts["total"] += 1
                counts[classification] += 1
                seen.add(digest)
                if classification == "exclude":
                    continue
                counts["included"] += 1
                files.append({
                    "sha256": digest,
                    "path": str(content_path),
                    "originalName": str(item.get("originalName") or content_path.name),
                    "captureFormat": capture_format,
                    "sizeBytes": expected_size,
                    "classification": classification,
                    "faultFamily": label.get("faultFamily"),
                    "labelRevision": label["revision"],
                    "reviewer": label["reviewer"],
                    "labelUpdatedAt": label["updatedAt"],
                })
        return {
            "schemaVersion": 1,
            "createdAt": utc_now(),
            "sourceImports": source_imports,
            "counts": counts,
            "files": files,
        }

    def summary(self) -> dict[str, Any]:
        imports: list[dict[str, Any]] = []
        ready_states: list[dict[str, Any]] = []
        unreadable = 0
        for import_dir in self._import_dirs():
            import_id = import_dir.name
            with self._lock:
                published = self._open_public.get(import_id)
            if published is not None:
                imports.append(dict(published))
                continue
            try:
                state = self._read_state(import_id)
                imports.append(self._public(state))
                if state.get("status") == "ready":
                    ready_states.append(state)
            except (OSError, ValueError, json.JSONDecodeError, DatasetServiceError):
                unreadable += 1
                continue
        imports.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
        ready = [item for item in imports if item.get("status") == "ready"]
        unique_content_bytes: dict[str, int] = {}
        for state in ready_states:
            for item in state.get("files") or []:
                if not isinstance(item, dict):
                    continue
                digest = item.get("sha256")
                size = item.get("sizeBytes")
                if (
                    isinstance(digest, str)
                    and SHA256_RE.fullmatch(digest)
                    and isinstance(size, int)
                    and size >= 0
                ):
                    unique_content_bytes.setdefault(digest, size)
        total_files = sum(int(item.get("fileCount") or 0) for item in ready)
        labeled_files = sum(int(item.get("labeledFileCount") or 0) for item in ready)
        return {
            "schemaVersion": 1,
            "storagePath": str(self.root),
            "schedule": {
                "cadence": "monthly",
                "nextWindowAt": _next_month_start(),
                "mode": "manual_approval",
            },
            "totals": {
                "imports": len(ready),
                "files": total_files,
                "bytes": sum(unique_content_bytes.values()),
                "duplicates": sum(int(item.get("duplicateCount") or 0) for item in ready),
                "rejected": sum(int(item.get("rejectedCount") or 0) for item in ready),
                "labeledFiles": labeled_files,
            },
            "readyForRetrain": False,
            "blocker": "training_pipeline_required" if total_files > 0 and labeled_files == total_files else "labels_and_training_pipeline_required",
            "unreadableImports": unreadable,
            # every import, newest first: Ground Truth and Train Model select from this list
            "imports": imports,
        }


__all__ = [
    "DatasetServiceError",
    "DatasetUpload",
    "MAX_UPLOAD_BYTES",
    "TrainingDatasetService",
]

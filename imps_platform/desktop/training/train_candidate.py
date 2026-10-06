"""Fine-tune the Desktop LSTM-AE and GRU candidate on reviewed PCAP data.

This worker runs under the separately installed ``ev_ai`` PyTorch environment.
Normal captures supply anomaly-model training windows, Fault captures are kept
out of optimization as an evaluation reserve, and Exclude captures never enter
the snapshot.  Output is a new candidate directory; production artifacts are
never modified here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


FLOAT_FIELDS = (
    "soc", "evse_v", "evse_i", "ev_target_v", "ev_target_i", "ev_max_v",
    "ev_max_i", "evse_max_v", "evse_max_i", "remaining_full_min",
    "remaining_bulk_min",
)
TEXT_FIELDS = (
    "session", "resp_code", "evse_status", "isolation", "notification",
    "ev_err", "ev_ready", "charge_complete", "bulk_complete",
    "evse_processing", "limit_achieved", "validation",
)
AE_WINDOW = 32
AE_STRIDE = 8
FORE_WINDOW = 16
FORE_STRIDE = 4
MAX_AE_WINDOWS = 20_000
MAX_FORE_WINDOWS = 50_000
SAMPLING_SEED = 0
REPLACE_ATTEMPTS = 8
REPLACE_BACKOFF_SECONDS = 0.05


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json_atomic(path: Path, payload: dict[str, Any], *, attempts: int = REPLACE_ATTEMPTS) -> None:
    """Write then replace. On Windows the replace fails while another process
    (the sidecar polling progress, or an on-access scanner) has the target open,
    so it is retried briefly before the error is raised."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    for attempt in range(attempts):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(REPLACE_BACKOFF_SECONDS * (attempt + 1))


def update_progress(path: Path, stage: str, progress: float, detail: str) -> None:
    """Progress is advisory: a failed write must never end a training run."""
    try:
        write_json_atomic(path, {
            "stage": stage,
            "progress": max(0.0, min(100.0, float(progress))),
            "detail": detail[:300],
            "updatedAt": utc_now(),
        })
    except OSError:
        pass


class WindowReservoir:
    """Seeded uniform sample (Algorithm R) of up to ``capacity`` windows.

    Every window of every Normal session has the same chance of being kept, so
    the cap is spread over the whole selection instead of filling from the first
    captures. ``sources`` records which (capture, session) each kept window came from.
    """

    def __init__(self, capacity: int, seed: int, np: Any) -> None:
        self.capacity = capacity
        self.items: list[Any] = []
        self.sources: list[tuple[int, int]] = []
        self.seen = 0
        self._np = np
        self._rng = np.random.default_rng(seed)

    def offer(self, count: int, build: Any, source: tuple[int, int]) -> None:
        if count <= 0:
            return
        positions = self._np.arange(self.seen + 1, self.seen + count + 1)
        draws = self._rng.integers(0, positions)
        self.seen += count
        for index in range(count):
            if len(self.items) < self.capacity:
                self.items.append(build(index))
                self.sources.append(source)
                continue
            slot = int(draws[index])
            if slot < self.capacity:
                self.items[slot] = build(index)
                self.sources[slot] = source


def session_windows(values: Any, np: Any, ae: WindowReservoir, fore: WindowReservoir, source: tuple[int, int]) -> None:
    """Offer one Normal session's windows to both reservoirs.

    The forecaster keeps the recipe the baseline was trained with: windows over
    every V2G event of the session (see DATASET_RETRAIN.md, "Forecaster windows").
    """
    ae_count = max(0, (len(values) - AE_WINDOW) // AE_STRIDE + 1) if len(values) >= AE_WINDOW else 0
    ae.offer(ae_count, lambda i: values[i * AE_STRIDE:i * AE_STRIDE + AE_WINDOW].copy(), source)
    fore_count = max(0, (len(values) - FORE_WINDOW - 1) // FORE_STRIDE + 1) if len(values) > FORE_WINDOW else 0
    if fore_count:
        features = np.asarray([fore_slice(vector) for vector in values], dtype=np.float32)
        targets = values[:, [6, 7]]
        fore.offer(
            fore_count,
            lambda i: (
                features[i * FORE_STRIDE:i * FORE_STRIDE + FORE_WINDOW].copy(),
                targets[i * FORE_STRIDE + FORE_WINDOW].copy(),
            ),
            source,
        )


def remove_telemetry(work: Path, digest: str) -> None:
    for leftover in work.glob(f"{digest}*"):
        try:
            leftover.unlink()
        except OSError:
            pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_version(source: Path) -> str:
    digest = hashlib.sha256()
    for name in ("lstm_ae.pt", "gru_fore.pt"):
        path = source / name
        digest.update(name.encode("ascii"))
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()[:16]


def telemetry_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("t"):
                continue
            row["t"] = float(row["t"])
            yield row


def row_to_event(row: dict[str, Any], event_class: Any) -> Any:
    values: dict[str, Any] = {
        "t": float(row["t"]),
        "kind": row.get("kind") or "",
        "msg": row.get("msg") or "",
    }
    for field in TEXT_FIELDS:
        values[field] = row.get(field) or ""
    for field in FLOAT_FIELDS:
        value = row.get(field)
        values[field] = float(value) if value not in (None, "") else None
    extra = row.get("extra")
    if extra:
        try:
            decoded = json.loads(extra)
            values["extra"] = decoded if isinstance(decoded, dict) else {}
        except (TypeError, json.JSONDecodeError):
            values["extra"] = {}
    return event_class(**values)


def fore_slice(vector: Any) -> list[float]:
    return [
        vector[6], vector[7], vector[8], vector[9], vector[10], vector[5],
        vector[28], vector[3],
    ]


def checkpoint_arrays(name: str, checkpoint: dict[str, Any], np: Any) -> dict[str, Any]:
    state = checkpoint.get("state")
    if not isinstance(state, dict) or not state:
        raise RuntimeError(f"{name}.pt contains no state dictionary")
    arrays = {
        str(key): np.asarray(value.detach().cpu().numpy(), dtype=np.float32)
        for key, value in state.items()
    }
    if any(not np.isfinite(array).all() for array in arrays.values()):
        raise RuntimeError(f"{name}.pt contains non-finite model weights")
    arrays["__err_mean"] = np.asarray(float(checkpoint["err_mean"]), dtype=np.float64)
    arrays["__err_std"] = np.asarray(float(checkpoint["err_std"]), dtype=np.float64)
    if name == "lstm_ae":
        arrays["__n_feat"] = np.asarray(int(checkpoint["n_feat"]), dtype=np.int64)
    return arrays


def write_npz_atomic(path: Path, arrays: dict[str, Any], np: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--portable-runtime-dir", type=Path, required=True)
    parser.add_argument("--ai-project", type=Path, required=True)
    parser.add_argument("--baseline-artifacts", type=Path, required=True)
    parser.add_argument("--tshark", type=Path, required=True)
    parser.add_argument("--epochs", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    if not 1 <= args.epochs <= 8:
        raise SystemExit("epochs must be between 1 and 8")
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != 1:
        raise SystemExit("training snapshot is invalid")
    files = snapshot.get("files")
    if not isinstance(files, list) or not files:
        raise SystemExit("training snapshot has no included captures")

    args.output.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    os.environ["EV_AI_ISO"] = "0"
    os.environ["EV_AI_ISO_VEC"] = "0"
    os.environ["EV_AI_ARTIFACTS"] = str(args.baseline_artifacts.resolve())
    os.environ.setdefault("PYTHONHASHSEED", "0")
    sys.path.insert(0, str(args.portable_runtime_dir.resolve()))
    sys.path.insert(0, str(args.ai_project.resolve()))

    update_progress(args.progress, "loading", 4, "Loading PyTorch and the verified baseline checkpoints")
    import numpy as np
    import torch
    import torch.nn as nn
    from capture import extract, iter_sessions
    from core.feature_tracker import FeatureTracker, FeatureState
    from core.schema import Event
    from models.nn_tools import GruForecaster, LstmAE

    torch.manual_seed(0)
    np.random.seed(0)
    torch.set_num_threads(1)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        torch.cuda.manual_seed_all(0)
    ae_reservoir = WindowReservoir(MAX_AE_WINDOWS, SAMPLING_SEED, np)
    fore_reservoir = WindowReservoir(MAX_FORE_WINDOWS, SAMPLING_SEED + 1, np)
    normal_sessions = fault_sessions = extracted_events = 0
    normal_captures = fault_captures = 0
    # content order, so the sample does not depend on which batch was ticked first
    files = sorted(files, key=lambda entry: str(entry.get("sha256") or "") if isinstance(entry, dict) else "")

    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise RuntimeError("training snapshot contains an invalid file entry")
        capture_path = Path(str(item.get("path") or "")).resolve(strict=True)
        digest = str(item.get("sha256") or "")
        if sha256_file(capture_path) != digest:
            raise RuntimeError(f"capture hash changed after snapshot: {capture_path.name}")
        classification = item.get("classification")
        if classification not in {"normal", "fault"}:
            raise RuntimeError("training snapshot contains an unsupported label")
        telemetry_path = args.work / f"{digest}.csv"
        update_progress(
            args.progress,
            "extracting",
            8 + 37 * index / max(1, len(files)),
            f"Decoding reviewed capture {index + 1:,}/{len(files):,}",
        )
        try:
            extracted_events += int(extract(str(capture_path), str(telemetry_path), args.tshark))
            session_count = 0
            for rows in iter_sessions(telemetry_rows(telemetry_path)):
                if classification == "fault":
                    if any(row.get("kind") == "v2g" for row in rows):
                        session_count += 1
                    continue
                tracker = FeatureTracker()
                sequence = []
                for row in rows:
                    event = row_to_event(row, Event)
                    state = tracker.update(event)
                    if event.kind == "v2g":
                        sequence.append(state.as_vector())
                if not sequence:
                    continue
                session_windows(
                    np.asarray(sequence, dtype=np.float32), np,
                    ae_reservoir, fore_reservoir, (index, session_count),
                )
                session_count += 1
        finally:
            # decoded telemetry is as large as the capture; keep only one at a time
            remove_telemetry(args.work, digest)
        if classification == "normal":
            normal_captures += 1
            normal_sessions += session_count
        else:
            fault_captures += 1
            fault_sessions += session_count

    update_progress(args.progress, "preparing", 47, "Building deterministic fine-tuning windows from Normal captures")
    ae_windows = np.asarray(ae_reservoir.items, dtype=np.float32)
    fore_x = np.asarray([pair[0] for pair in fore_reservoir.items], dtype=np.float32)
    fore_y = np.asarray([pair[1] for pair in fore_reservoir.items], dtype=np.float32)
    contributing = set(ae_reservoir.sources) | set(fore_reservoir.sources)
    contributing_captures = len({capture for capture, _ in contributing})
    if len(ae_windows) == 0:
        raise RuntimeError("Normal captures contain no session with at least 32 V2G events")
    if len(fore_x) == 0:
        raise RuntimeError("Normal captures contain no session with enough data for the GRU forecaster")

    if not np.isfinite(ae_windows).all() or not np.isfinite(fore_x).all() or not np.isfinite(fore_y).all():
        raise RuntimeError("training data contains non-finite feature values")

    baseline_ae = torch.load(args.baseline_artifacts / "lstm_ae.pt", map_location="cpu", weights_only=True)
    baseline_fore = torch.load(args.baseline_artifacts / "gru_fore.pt", map_location="cpu", weights_only=True)
    if int(baseline_ae.get("n_feat", 0)) != FeatureState.N_FEATURES:
        raise RuntimeError("baseline LSTM feature width does not match the Desktop baseline policy")

    def train_autoencoder() -> tuple[dict[str, Any], float, float]:
        model = LstmAE(FeatureState.N_FEATURES).to(device)
        model.load_state_dict(baseline_ae["state"])
        optimizer = torch.optim.Adam(model.parameters(), lr=2e-4)
        dataset = torch.from_numpy(ae_windows)

        def loss_value() -> float:
            model.eval()
            total = 0.0
            with torch.no_grad():
                for offset in range(0, len(dataset), 512):
                    batch = dataset[offset:offset + 512].to(device)
                    total += float(((model(batch) - batch) ** 2).mean()) * len(batch)
            return total / len(dataset)

        initial = loss_value()
        model.train()
        for epoch in range(args.epochs):
            generator = torch.Generator().manual_seed(epoch)
            order = torch.randperm(len(dataset), generator=generator)
            for offset in range(0, len(dataset), 256):
                batch = dataset[order[offset:offset + 256]].to(device)
                loss = ((model(batch) - batch) ** 2).mean()
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
            update_progress(args.progress, "training_lstm", 50 + 20 * (epoch + 1) / args.epochs, f"Fine-tuning LSTM-AE epoch {epoch + 1}/{args.epochs}")
        final = loss_value()
        model.eval()
        errors = []
        with torch.no_grad():
            for offset in range(0, len(dataset), 512):
                batch = dataset[offset:offset + 512].to(device)
                errors.append(((model(batch) - batch) ** 2).mean(dim=(1, 2)).cpu().numpy())
        values = np.concatenate(errors)
        checkpoint = {
            "state": model.state_dict(),
            "n_feat": FeatureState.N_FEATURES,
            "err_mean": float(values.mean()),
            "err_std": float(values.std() + 1e-9),
        }
        return checkpoint, initial, final

    def train_forecaster() -> tuple[dict[str, Any], float, float]:
        model = GruForecaster().to(device)
        model.load_state_dict(baseline_fore["state"])
        optimizer = torch.optim.Adam(model.parameters(), lr=2e-4)
        inputs = torch.from_numpy(fore_x)
        targets = torch.from_numpy(fore_y)

        def loss_value() -> float:
            model.eval()
            total = 0.0
            with torch.no_grad():
                for offset in range(0, len(inputs), 1024):
                    x = inputs[offset:offset + 1024].to(device)
                    y = targets[offset:offset + 1024].to(device)
                    total += float(((model(x) - y) ** 2).mean()) * len(x)
            return total / len(inputs)

        initial = loss_value()
        model.train()
        for epoch in range(args.epochs):
            generator = torch.Generator().manual_seed(100 + epoch)
            order = torch.randperm(len(inputs), generator=generator)
            for offset in range(0, len(inputs), 512):
                selected = order[offset:offset + 512]
                x = inputs[selected].to(device)
                y = targets[selected].to(device)
                loss = ((model(x) - y) ** 2).mean()
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
            update_progress(args.progress, "training_gru", 72 + 16 * (epoch + 1) / args.epochs, f"Fine-tuning GRU forecaster epoch {epoch + 1}/{args.epochs}")
        final = loss_value()
        model.eval()
        errors = []
        with torch.no_grad():
            for offset in range(0, len(inputs), 1024):
                x = inputs[offset:offset + 1024].to(device)
                prediction = model(x).cpu().numpy()
                errors.append(np.abs(prediction - fore_y[offset:offset + 1024]).mean(axis=1))
        values = np.concatenate(errors)
        checkpoint = {
            "state": model.state_dict(),
            "err_mean": float(values.mean()),
            "err_std": float(values.std() + 1e-9),
        }
        return checkpoint, initial, final

    lstm_checkpoint, ae_initial, ae_final = train_autoencoder()
    gru_checkpoint, fore_initial, fore_final = train_forecaster()
    if not all(math.isfinite(value) and value >= 0 for value in (ae_initial, ae_final, fore_initial, fore_final)):
        raise RuntimeError("training produced invalid loss metrics")
    update_progress(args.progress, "exporting", 91, "Exporting safe NumPy candidate artifacts")
    torch.save(lstm_checkpoint, args.output / "lstm_ae.pt")
    torch.save(gru_checkpoint, args.output / "gru_fore.pt")
    write_npz_atomic(args.output / "lstm_ae.npz", checkpoint_arrays("lstm_ae", lstm_checkpoint, np), np)
    write_npz_atomic(args.output / "gru_fore.npz", checkpoint_arrays("gru_fore", gru_checkpoint, np), np)
    version = artifact_version(args.output)
    file_manifest = {}
    for name in ("lstm_ae.npz", "gru_fore.npz"):
        path = args.output / name
        with np.load(path, allow_pickle=False) as archive:
            if "__err_mean" not in archive.files:
                raise RuntimeError(f"candidate artifact is invalid: {name}")
        file_manifest[name] = {"sha256": sha256_file(path), "sizeBytes": path.stat().st_size}
    manifest = {
        "schemaVersion": 1,
        "artifactVersion": version,
        "format": "numpy-npz-no-pickle",
        "createdAt": utc_now(),
        "files": file_manifest,
    }
    write_json_atomic(args.output / "manifest.json", manifest)
    candidate = {
        "artifactVersion": version,
        "createdAt": manifest["createdAt"],
        "approvalStatus": "manual_validation_required",
        "training": {
            "device": device,
            "deviceName": torch.cuda.get_device_name(0) if device == "cuda" else "CPU",
            "epochs": args.epochs,
            "normalCaptures": normal_captures,
            "faultReserveCaptures": fault_captures,
            "normalSessions": normal_sessions,
            "faultReserveSessions": fault_sessions,
            "extractedEvents": extracted_events,
            "aeWindows": int(len(ae_windows)),
            "forecasterWindows": int(len(fore_x)),
            "aeWindowsAvailable": int(ae_reservoir.seen),
            "forecasterWindowsAvailable": int(fore_reservoir.seen),
            "contributingCaptures": contributing_captures,
            "contributingSessions": len(contributing),
            "aeLossInitial": ae_initial,
            "aeLossFinal": ae_final,
            "forecasterLossInitial": fore_initial,
            "forecasterLossFinal": fore_final,
            "durationSeconds": max(0.0, time.perf_counter() - started),
        },
        "files": file_manifest,
    }
    write_json_atomic(args.result, {"schemaVersion": 1, "candidate": candidate}, attempts=40)
    update_progress(args.progress, "complete", 100, "Candidate model is ready for manual validation")
    print(json.dumps({"artifactVersion": version, "device": device}, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        try:
            parsed = parse_args()
            update_progress(parsed.progress, "failed", 100, str(exc))
        except Exception:
            pass
        raise

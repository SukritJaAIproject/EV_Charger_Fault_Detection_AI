"""Convert trusted Torch checkpoints into safe NumPy-only desktop artifacts.

Run this script with the existing ``ev_ai`` Python environment.  Torch is a
build-time dependency only; the generated NPZ files are loaded with
``allow_pickle=False`` by the installed application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch


EXPECTED_ARTIFACT_VERSION = "53b6f14244c2e633"
MODEL_NAMES = ("lstm_ae", "gru_fore")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def source_artifact_version(source: Path) -> str:
    digest = hashlib.sha256()
    for name in ("lstm_ae.pt", "gru_fore.pt"):
        path = source / name
        if not path.is_file():
            raise SystemExit(f"Missing source checkpoint: {path}")
        digest.update(name.encode("ascii"))
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()[:16]


def _checkpoint_arrays(name: str, checkpoint: dict[str, Any]) -> dict[str, np.ndarray]:
    state = checkpoint.get("state")
    if not isinstance(state, dict) or not state:
        raise SystemExit(f"{name}.pt does not contain a state dictionary")
    arrays = {
        str(key): np.asarray(value.detach().cpu().numpy(), dtype=np.float32)
        for key, value in state.items()
    }
    for metadata in ("err_mean", "err_std"):
        value = float(checkpoint[metadata])
        if not np.isfinite(value):
            raise SystemExit(f"{name}.pt contains invalid {metadata}")
        arrays[f"__{metadata}"] = np.asarray(value, dtype=np.float64)
    if name == "lstm_ae":
        n_feat = int(checkpoint.get("n_feat", 0))
        if n_feat <= 0:
            raise SystemExit("lstm_ae.pt contains an invalid n_feat")
        arrays["__n_feat"] = np.asarray(n_feat, dtype=np.int64)
    return arrays


def _write_npz_atomic(path: Path, arrays: dict[str, np.ndarray]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(r"G:\ev_charger_ai_data_v4\artifacts"),
        help="directory containing lstm_ae.pt and gru_fore.pt",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / ".desktop-build" / "models",
    )
    parser.add_argument(
        "--expected-artifact-version",
        default=EXPECTED_ARTIFACT_VERSION,
        help="fail closed when the source checkpoints are not the audited pair",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    version = source_artifact_version(source)
    if version != args.expected_artifact_version:
        raise SystemExit(
            f"Source artifactVersion is {version}, expected "
            f"{args.expected_artifact_version}"
        )

    output.mkdir(parents=True, exist_ok=True)
    file_manifest: dict[str, dict[str, Any]] = {}
    for model_name in MODEL_NAMES:
        source_path = source / f"{model_name}.pt"
        checkpoint = torch.load(
            source_path, map_location="cpu", weights_only=False
        )
        if not isinstance(checkpoint, dict):
            raise SystemExit(f"Unexpected checkpoint payload: {source_path}")
        destination = output / f"{model_name}.npz"
        _write_npz_atomic(
            destination, _checkpoint_arrays(model_name, checkpoint)
        )
        # Prove that the runtime-safe deserializer can open every array.
        with np.load(destination, allow_pickle=False) as archive:
            if not archive.files or "__err_mean" not in archive.files:
                raise SystemExit(f"Converted artifact failed validation: {destination}")
        file_manifest[destination.name] = {
            "sha256": sha256_file(destination),
            "sizeBytes": destination.stat().st_size,
        }

    manifest = {
        "schemaVersion": 1,
        "artifactVersion": version,
        "format": "numpy-npz-no-pickle",
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": file_manifest,
    }
    _write_json_atomic(output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "artifactVersion": version,
                "output": str(output),
                "files": sorted(file_manifest),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

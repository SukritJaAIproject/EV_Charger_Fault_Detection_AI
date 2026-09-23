"""Export the validated fault-detection summary for the Windows desktop bundle.

This build helper deliberately uses only the Python standard library.  The
FastAPI symbols imported by the normal router are stubbed because the exporter
only calls its pure result loader; no web routes are started here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_DATA_FILES = (
    Path("results/leaderboard_test.json"),
    Path("results/analysis_test.json"),
    Path("results/records_test.json"),
    Path("split.json"),
)


class _Router:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    @staticmethod
    def _decorator(*_args: Any, **_kwargs: Any):
        return lambda function: function

    get = _decorator
    post = _decorator


def _install_fastapi_stubs() -> None:
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = _Router
    fastapi.Depends = lambda dependency: dependency
    fastapi.HTTPException = RuntimeError
    fastapi.Request = object
    fastapi.Response = object
    responses = types.ModuleType("fastapi.responses")
    responses.JSONResponse = dict
    sys.modules["fastapi"] = fastapi
    sys.modules["fastapi.responses"] = responses


def _is_data_root(path: Path) -> bool:
    return all((path / relative).is_file() for relative in REQUIRED_DATA_FILES)


def _resolve_data_root(explicit: Path | None) -> Path:
    # A supplied root is the one the caller means (it also decides the edition's
    # detection policy), so an incomplete one is an error, never a fallback.
    env_root = os.environ.get("IMPS_FAULT_DATA_ROOT")
    supplied = explicit if explicit is not None else (Path(env_root) if env_root else None)
    if supplied is not None:
        missing = [str(supplied / relative) for relative in REQUIRED_DATA_FILES if not (supplied / relative).is_file()]
        if missing:
            raise SystemExit(f"Data root {supplied} is incomplete; missing: {', '.join(missing)}")
        return supplied.resolve()
    candidates = [
        Path(r"G:\ev_charger_ai_data_v4"),
        Path(r"G:\ev_charger_ai_data"),
        Path(r"E:\ev_charger_ai_data"),
    ]
    for candidate in candidates:
        if candidate is not None and _is_data_root(candidate):
            return candidate.resolve()
    locations = ", ".join(str(path) for path in candidates if path is not None)
    raise SystemExit(f"Validated benchmark data was not found. Checked: {locations}")


def _detection_policy(data_root: Path) -> dict[str, Any] | None:
    """The policy block of the replay that produced this data root, if any.

    A replay run with rule layers switched on writes results/run_manifest.json
    with a detectionPolicy block; the desktop sidecar runs the detector under
    the same policy, so it is copied into the summary next to the benchmark
    it describes. No manifest (the published v4 root) means the baseline.
    """
    manifest_path = data_root / "results" / "run_manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    block = manifest.get("detectionPolicy")
    if block is None:
        return None
    if not isinstance(block, dict) or not isinstance(block.get("id"), str):
        raise SystemExit(f"{manifest_path} has an invalid detectionPolicy block")
    # the id is the only source of truth; the flags come from the sidecar's
    # whitelist and must agree with what the replay manifest recorded
    sys.path.insert(0, str(PROJECT_ROOT / "desktop" / "runtime"))
    import detection_policy

    policy_id = block["id"].strip()
    if policy_id not in detection_policy.POLICIES:
        raise SystemExit(f"{manifest_path}: unknown detection policy {policy_id!r}")
    public = detection_policy.public(policy_id)
    for key in ("iso2Rules", "slacRuleMode"):
        if key in block and block[key] != public[key]:
            raise SystemExit(f"{manifest_path}: {key}={block[key]!r} does not match policy {policy_id!r} ({public[key]!r})")
    return {"schemaVersion": 1, **public}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument(
        "--train-records",
        type=Path,
        default=None,
        help="records of the in-sample baseline replay over the training stations (adds analysis.byStationTrain)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / ".desktop-build" / "summary.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_root = _resolve_data_root(args.data_root)
    _install_fastapi_stubs()
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from desktop.fault_detection_api import _load_results_module

    results_module = _load_results_module(PROJECT_ROOT)
    summary, etag = results_module.load_fault_detection_summary(
        data_root, train_records=args.train_records
    )
    if summary.get("source") != "full_fleet":
        raise SystemExit("Expected a validated full_fleet summary")
    if len(summary.get("leaderboard", [])) != 5:
        raise SystemExit("Expected exactly five benchmark models")
    if summary.get("dataset", {}).get("sessions") != 8_820:
        raise SystemExit("Expected exactly 8,820 held-out sessions")
    if len(summary.get("analysis", {}).get("byStation", [])) != 45:
        raise SystemExit("Expected exactly 45 held-out station summaries")
    if any(row.get("split") != "test" for row in summary["analysis"]["byStation"]):
        raise SystemExit("Every held-out station row must be marked split=test")
    train_rows = summary["analysis"].get("byStationTrain")
    if args.train_records is not None:
        if not train_rows or any(row.get("split") != "train" for row in train_rows):
            raise SystemExit("Expected training-station rows marked split=train")
    policy = _detection_policy(data_root)
    if policy is not None:
        if args.train_records is not None and policy["id"] != "baseline":
            # the training-station replay runs the baseline detector; its rows
            # would misdescribe an edition that runs another policy
            raise SystemExit(f"--train-records is a baseline replay; it cannot be bundled with policy {policy['id']!r}")
        summary["detectionPolicy"] = policy

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(
        json.dumps(
            {
                "output": str(output),
                "bytes": output.stat().st_size,
                "stations": len(summary["analysis"]["byStation"]),
                "trainStations": len(summary["analysis"].get("byStationTrain") or []),
                "detectionPolicy": (summary.get("detectionPolicy") or {}).get("id", "baseline"),
                "models": len(summary["leaderboard"]),
                "etag": etag,
                "dataRoot": str(data_root),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

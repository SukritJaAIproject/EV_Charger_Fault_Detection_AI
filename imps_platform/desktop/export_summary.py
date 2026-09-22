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
    candidates = [
        explicit,
        Path(os.environ["IMPS_FAULT_DATA_ROOT"]) if os.environ.get("IMPS_FAULT_DATA_ROOT") else None,
        Path(r"G:\ev_charger_ai_data_v4"),
        Path(r"G:\ev_charger_ai_data"),
        Path(r"E:\ev_charger_ai_data"),
    ]
    for candidate in candidates:
        if candidate is not None and _is_data_root(candidate):
            return candidate.resolve()
    locations = ", ".join(str(path) for path in candidates if path is not None)
    raise SystemExit(f"Validated benchmark data was not found. Checked: {locations}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
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
    summary, etag = results_module.load_fault_detection_summary(data_root)
    if summary.get("source") != "full_fleet":
        raise SystemExit("Expected a validated full_fleet summary")
    if len(summary.get("leaderboard", [])) != 5:
        raise SystemExit("Expected exactly five benchmark models")
    if summary.get("dataset", {}).get("sessions") != 8_820:
        raise SystemExit("Expected exactly 8,820 held-out sessions")
    if len(summary.get("analysis", {}).get("byStation", [])) != 45:
        raise SystemExit("Expected exactly 45 station summaries")

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

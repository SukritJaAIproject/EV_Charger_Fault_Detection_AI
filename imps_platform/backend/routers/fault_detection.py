"""Read-only API for the completed full-fleet charger fault benchmark."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from deps import UserClaims, get_current_user

try:
    from services.fault_detection_jobs import JobServiceError, PcapJobService
except ModuleNotFoundError:  # Loaded directly by the standalone desktop server.
    from backend.services.fault_detection_jobs import JobServiceError, PcapJobService


router = APIRouter(prefix="/ai/fault-detection", tags=["AI fault detection"])
log = logging.getLogger("uvicorn.error")

_DEFAULT_DATA_ROOT = Path(r"G:\ev_charger_ai_data_v4")
_RESULTS_DIR = "results"
_LEADERBOARD_FILE = "leaderboard_test.json"
_ANALYSIS_FILE = "analysis_test.json"
_RECORDS_FILE = "records_test.json"
_SPLIT_FILE = "split.json"
_MAX_RESULT_BYTES = 10 * 1024 * 1024
# records of the in-sample replay over the training stations (optional, desktop
# builds only): ~31,800 sessions, so ~20 MB with five detectors
_MAX_TRAIN_RECORDS_BYTES = 64 * 1024 * 1024
_LATE_GRACE_SECONDS = 10.0
_LEAD_CAP_SECONDS = 120.0
_JOB_SERVICE: PcapJobService | None = None

_MODEL_META: tuple[dict[str, Any], ...] = (
    {
        "raw": "TraditionalAI",
        "id": "traditional",
        "name": "Traditional AI",
        "family": "Statistical & tree-based baseline",
        "description": {
            "th": "โมเดลฐานสำหรับเทียบความแม่นยำ ความเร็ว และต้นทุนการประมวลผล",
            "en": "Baseline models for accuracy, latency, and compute-cost comparison.",
        },
        "color": "#0284c7",
    },
    {
        "raw": "RL",
        "id": "rl",
        "name": "RL / DQN",
        "family": "Sequential decision policy",
        "description": {
            "th": "เรียนรู้นโยบายการแจ้งเตือนจากลำดับเหตุการณ์ใน charging session",
            "en": "Learns an alerting policy from the charging-session event sequence.",
        },
        "color": "#7c3aed",
    },
    {
        "raw": "AIAgent",
        "id": "ai-agent",
        "name": "AI Agent",
        "family": "Detector with diagnostic tools",
        "description": {
            "th": "ใช้โมเดลร่วมกับเครื่องมือวิเคราะห์หลักฐานและระบุสาเหตุที่เป็นไปได้",
            "en": "Combines a detector with evidence tools and probable-cause analysis.",
        },
        "color": "#059669",
    },
    {
        "raw": "AgenticAI",
        "id": "agentic-ai",
        "name": "Agentic AI",
        "family": "Plan · verify · decide",
        "description": {
            "th": "วางแผนตรวจสอบ เรียกใช้เครื่องมือ และทบทวนหลักฐานก่อนตัดสินใจ",
            "en": "Plans an investigation, calls tools, and verifies evidence before deciding.",
        },
        "color": "#d97706",
    },
    {
        "raw": "MultiAgent",
        "id": "multi-agent",
        "name": "Multi-Agent",
        "family": "Specialists with consensus",
        "description": {
            "th": "รวมผลจาก agent ผู้เชี่ยวชาญหลายบทบาทด้วยกลไก consensus",
            "en": "Combines specialist agents through an evidence-based consensus layer.",
        },
        "color": "#db2777",
    },
)
_META_BY_RAW = {item["raw"]: item for item in _MODEL_META}
_EXPECTED_MODELS = set(_META_BY_RAW)
_FAMILY_ORDER = (
    "PROTOCOL_FAILED",
    "SESSION_ABORT",
    "SLAC_FAILURE",
    "EVSE_FAULT",
    "ISOLATION_FAULT",
    "EV_ERROR",
    "COMM_FREEZE",
)
_SOURCE_ORDER = ("legacy", "main", "v2g2024", "v2g2025")
_PIPELINE = (
    ("extract_pass1", "Extract 01"),
    ("extract_pass2", "Extract 02"),
    ("sessionize", "Sessionize"),
    ("split", "Data split"),
    ("dataset", "Dataset"),
    ("train_traditional", "Traditional"),
    ("train_nn_tools", "NN + Tools"),
    ("train_rl", "RL / DQN"),
    ("benchmark", "Benchmark"),
    ("analyze", "Analysis"),
)


class FaultDetectionResultError(ValueError):
    """The benchmark output is missing, malformed, or internally inconsistent."""


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise FaultDetectionResultError(f"{label} must be a JSON object")
    return value


def _as_int(value: Any, label: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FaultDetectionResultError(f"{label} must be a non-negative integer")
    if maximum is not None and value > maximum:
        raise FaultDetectionResultError(f"{label} cannot exceed {maximum}")
    return value


def _as_number(
    value: Any,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FaultDetectionResultError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise FaultDetectionResultError(f"{label} must be finite")
    if minimum is not None and result < minimum:
        raise FaultDetectionResultError(f"{label} cannot be below {minimum}")
    if maximum is not None and result > maximum:
        raise FaultDetectionResultError(f"{label} cannot exceed {maximum}")
    return result


def _read_result(path: Path) -> tuple[Mapping[str, Any], bytes, int]:
    try:
        raw = path.read_bytes()
        modified_ns = path.stat().st_mtime_ns
    except (OSError, PermissionError) as exc:
        raise FaultDetectionResultError(f"cannot read {path.name}") from exc
    if not raw or len(raw) > _MAX_RESULT_BYTES:
        raise FaultDetectionResultError(f"{path.name} has an invalid size")
    try:
        decoded = json.loads(
            raw.decode("utf-8-sig"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                FaultDetectionResultError(f"{path.name} contains {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaultDetectionResultError(f"{path.name} is not valid UTF-8 JSON") from exc
    return _as_mapping(decoded, path.name), raw, modified_ns


def _read_records(path: Path, max_bytes: int = _MAX_RESULT_BYTES) -> tuple[list[Any], bytes, int]:
    """Read the fixed per-session benchmark records used for station rollups."""
    try:
        raw = path.read_bytes()
        modified_ns = path.stat().st_mtime_ns
    except (OSError, PermissionError) as exc:
        raise FaultDetectionResultError(f"cannot read {path.name}") from exc
    if not raw or len(raw) > max_bytes:
        raise FaultDetectionResultError(f"{path.name} has an invalid size")
    try:
        decoded = json.loads(
            raw.decode("utf-8-sig"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                FaultDetectionResultError(f"{path.name} contains {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaultDetectionResultError(f"{path.name} is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, list) or not decoded:
        raise FaultDetectionResultError(f"{path.name} must be a non-empty JSON array")
    return decoded, raw, modified_ns


def _new_station_rollup() -> dict[str, Any]:
    return {
        "sessions": 0,
        "faultySessions": 0,
        "normalSessions": 0,
        "alertedSessions": 0,
        "tp": 0,
        "late": 0,
        "miss": 0,
        "fp": 0,
        "leads": [],
        "earlinessSum": 0.0,
        "faultFamilies": {},
    }


def _add_station_rollup(
    stats: dict[str, Any],
    *,
    family: str | None,
    outcome: str,
    lead: float | None,
) -> None:
    stats["sessions"] += 1
    if family is None:
        stats["normalSessions"] += 1
        if outcome == "fp":
            stats["fp"] += 1
            stats["alertedSessions"] += 1
        return

    stats["faultySessions"] += 1
    stats["faultFamilies"][family] = stats["faultFamilies"].get(family, 0) + 1
    if outcome == "tp":
        if lead is None:
            raise FaultDetectionResultError("on-time detection is missing its lead time")
        stats["tp"] += 1
        stats["alertedSessions"] += 1
        stats["leads"].append(lead)
        stats["earlinessSum"] += min(lead, _LEAD_CAP_SECONDS) / _LEAD_CAP_SECONDS
    elif outcome == "late":
        stats["late"] += 1
        stats["alertedSessions"] += 1
    else:
        stats["miss"] += 1


def _station_rollup_metrics(stats: Mapping[str, Any]) -> dict[str, Any]:
    sessions = stats["sessions"]
    faulty = stats["faultySessions"]
    normal = stats["normalSessions"]
    recall = stats["tp"] / faulty if faulty else 0.0
    far = stats["fp"] / normal if normal else 0.0
    earliness = stats["earlinessSum"] / faulty if faulty else 0.0
    precision_denominator = stats["tp"] + stats["fp"]
    precision = stats["tp"] / precision_denominator if precision_denominator else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    leads = sorted(stats["leads"])
    median_lead = leads[len(leads) // 2] if leads else 0.0
    families = sorted(
        stats["faultFamilies"].items(), key=lambda item: (-item[1], item[0])
    )
    return {
        "sessions": sessions,
        "faultySessions": faulty,
        "normalSessions": normal,
        "alertedSessions": stats["alertedSessions"],
        "faultRate": faulty / sessions * 100 if sessions else 0.0,
        "score": 50 * recall + 30 * (1 - far) + 20 * earliness,
        "recall": recall * 100,
        "falseAlarmRate": far * 100,
        "precision": precision * 100,
        "f1": f1 * 100,
        "medianLeadSeconds": median_lead,
        "tp": stats["tp"],
        "late": stats["late"],
        "miss": stats["miss"],
        "fp": stats["fp"],
        "topFaultFamily": families[0][0] if families else None,
    }


def _build_station_analysis(
    records: list[Any],
    *,
    split_name: str = "test",
    source_label: str = _RECORDS_FILE,
) -> list[dict[str, Any]]:
    """Aggregate AgenticAI's per-session results with the competition's exact rules.

    Every row carries the split it came from: "test" rows are the held-out
    evaluation, "train" rows are in-sample (the models were fitted on them).
    """
    stations: dict[str, dict[str, Any]] = {}
    for index, raw_record in enumerate(records):
        record_label = f"{source_label}[{index}]"
        record = _as_mapping(raw_record, record_label)
        label = _as_mapping(record.get("label"), f"{record_label}.label")
        station = label.get("station")
        if not isinstance(station, str) or not station.strip():
            raise FaultDetectionResultError(f"{record_label}.label.station is invalid")
        station = station.strip()
        connector = label.get("connector")
        if not isinstance(connector, str) or not connector.strip():
            raise FaultDetectionResultError(f"{record_label}.label.connector is invalid")
        group = label.get("group")
        if not isinstance(group, str) or not group.strip():
            raise FaultDetectionResultError(f"{record_label}.label.group is invalid")
        faults = label.get("faults")
        if not isinstance(faults, list):
            raise FaultDetectionResultError(f"{record_label}.label.faults must be an array")
        alerts = _as_mapping(record.get("alerts"), f"{record_label}.alerts")
        raw_alert = alerts.get("AgenticAI")
        alert_time: float | None = None
        if raw_alert is not None:
            alert = _as_mapping(raw_alert, f"{record_label}.alerts.AgenticAI")
            alert_time = _as_number(alert.get("t"), f"{record_label}.alerts.AgenticAI.t")

        stats = stations.setdefault(
            station,
            {
                "station": station,
                "group": group.strip(),
                "connectors": set(),
                "rollup": _new_station_rollup(),
                "connectorRollups": {},
                "familyRollups": {},
            },
        )
        if stats["group"] != group.strip():
            raise FaultDetectionResultError(f"{station} appears in multiple source groups")
        connector = connector.strip()
        stats["connectors"].add(connector)
        connector_stats = stats["connectorRollups"].setdefault(
            connector, _new_station_rollup()
        )

        family: str | None = None
        fault_time: float | None = None
        fault_detail: str | None = None
        if faults:
            parsed_faults: list[tuple[float, str, str]] = []
            for fault_index, raw_fault in enumerate(faults):
                fault_path = f"{record_label}.label.faults[{fault_index}]"
                if not isinstance(raw_fault, (list, tuple)) or len(raw_fault) < 2:
                    raise FaultDetectionResultError(f"{fault_path} is invalid")
                fault_time = _as_number(raw_fault[0], f"{fault_path}[0]")
                family = raw_fault[1]
                if not isinstance(family, str) or not family:
                    raise FaultDetectionResultError(f"{fault_path}[1] is invalid")
                raw_detail = raw_fault[2] if len(raw_fault) >= 3 else family
                if not isinstance(raw_detail, str) or not raw_detail.strip():
                    raise FaultDetectionResultError(f"{fault_path}[2] is invalid")
                if len(raw_detail) > 500:
                    raise FaultDetectionResultError(f"{fault_path}[2] is too long")
                parsed_faults.append((fault_time, family, raw_detail.strip()))
            fault_time, family, fault_detail = min(parsed_faults, key=lambda item: item[0])
            if alert_time is None:
                outcome = "miss"
                lead = None
            elif alert_time <= fault_time + _LATE_GRACE_SECONDS:
                lead = max(0.0, fault_time - alert_time)
                outcome = "tp"
            else:
                outcome = "late"
                lead = None
        else:
            outcome = "fp" if alert_time is not None else "tn"
            lead = None

        _add_station_rollup(stats["rollup"], family=family, outcome=outcome, lead=lead)
        _add_station_rollup(connector_stats, family=family, outcome=outcome, lead=lead)
        if family is not None:
            family_stats = stats["familyRollups"].setdefault(
                family,
                {
                    "family": family,
                    "faultySessions": 0,
                    "tp": 0,
                    "late": 0,
                    "miss": 0,
                    "leads": [],
                    "evidenceCounts": {},
                },
            )
            family_stats["faultySessions"] += 1
            family_stats[outcome] += 1
            family_stats["evidenceCounts"][fault_detail] = (
                family_stats["evidenceCounts"].get(fault_detail, 0) + 1
            )
            if outcome == "tp":
                family_stats["leads"].append(lead)

    rows: list[dict[str, Any]] = []
    for station in sorted(stations):
        stats = stations[station]
        station_metrics = _station_rollup_metrics(stats["rollup"])
        connector_rows = []
        for connector in sorted(stats["connectorRollups"]):
            connector_rows.append(
                {
                    "connector": connector,
                    **_station_rollup_metrics(stats["connectorRollups"][connector]),
                }
            )

        family_rows = []
        for family in _ordered_names(set(stats["familyRollups"]), _FAMILY_ORDER):
            family_stats = stats["familyRollups"][family]
            faulty = family_stats["faultySessions"]
            family_leads = sorted(family_stats["leads"])
            top_evidence = [
                {"detail": detail, "count": count}
                for detail, count in sorted(
                    family_stats["evidenceCounts"].items(),
                    key=lambda item: (-item[1], item[0]),
                )[:3]
            ]
            family_rows.append(
                {
                    "family": family,
                    "faultySessions": faulty,
                    "tp": family_stats["tp"],
                    "late": family_stats["late"],
                    "miss": family_stats["miss"],
                    "recall": family_stats["tp"] / faulty * 100 if faulty else 0.0,
                    "medianLeadSeconds": (
                        family_leads[len(family_leads) // 2] if family_leads else 0.0
                    ),
                    "topEvidence": top_evidence,
                }
            )

        connector_totals = {
            key: sum(row[key] for row in connector_rows)
            for key in (
                "sessions",
                "faultySessions",
                "normalSessions",
                "alertedSessions",
                "tp",
                "late",
                "miss",
                "fp",
            )
        }
        expected_connector_totals = {
            key: station_metrics[key] for key in connector_totals
        }
        if connector_totals != expected_connector_totals:
            raise FaultDetectionResultError(
                f"{station} connector counts do not match the station result"
            )

        family_totals = {
            key: sum(row[key] for row in family_rows)
            for key in ("faultySessions", "tp", "late", "miss")
        }
        expected_family_totals = {key: station_metrics[key] for key in family_totals}
        if family_totals != expected_family_totals:
            raise FaultDetectionResultError(
                f"{station} fault-family counts do not match the station result"
            )

        rows.append(
            {
                "station": station,
                "split": split_name,
                "group": stats["group"],
                "connectors": len(stats["connectors"]),
                **station_metrics,
                "byConnector": connector_rows,
                "byFaultFamily": family_rows,
            }
        )
    return rows


def _validate_detector_names(detectors: Mapping[str, Any], label: str) -> None:
    actual = set(detectors)
    if actual != _EXPECTED_MODELS:
        missing = sorted(_EXPECTED_MODELS - actual)
        unexpected = sorted(actual - _EXPECTED_MODELS)
        raise FaultDetectionResultError(
            f"{label} detector set mismatch (missing={missing}, unexpected={unexpected})"
        )


def _public_metrics(
    raw: Any,
    label: str,
    *,
    n_faulty: int,
    n_clean: int,
) -> dict[str, Any]:
    data = _as_mapping(raw, label)
    recall = _as_number(data.get("recall"), f"{label}.recall", minimum=0, maximum=1)
    far = _as_number(data.get("far"), f"{label}.far", minimum=0, maximum=1)
    earliness = _as_number(
        data.get("earliness"), f"{label}.earliness", minimum=0, maximum=1
    )
    score = _as_number(data.get("score"), f"{label}.score", minimum=0, maximum=100)
    tp = _as_int(data.get("tp"), f"{label}.tp", maximum=n_faulty)
    late = _as_int(data.get("late"), f"{label}.late", maximum=n_faulty)
    miss = _as_int(data.get("miss"), f"{label}.miss", maximum=n_faulty)
    fp = _as_int(data.get("fp"), f"{label}.fp", maximum=n_clean)
    median_lead = _as_number(
        data.get("median_lead_s"), f"{label}.median_lead_s", minimum=0
    )
    mean_lead = _as_number(
        data.get("mean_lead_s"), f"{label}.mean_lead_s", minimum=0
    )
    wins = _as_number(data.get("wins"), f"{label}.wins", minimum=0)

    if tp + late + miss != n_faulty:
        raise FaultDetectionResultError(f"{label} fault counts do not add up")
    expected_recall = tp / n_faulty if n_faulty else 0.0
    expected_far = fp / n_clean if n_clean else 0.0
    if not math.isclose(recall, expected_recall, abs_tol=1e-9):
        raise FaultDetectionResultError(f"{label}.recall is inconsistent with tp")
    if not math.isclose(far, expected_far, abs_tol=1e-9):
        raise FaultDetectionResultError(f"{label}.far is inconsistent with fp")

    precision = tp / (tp + fp) if tp + fp else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "score": score,
        "recall": recall * 100,
        "falseAlarmRate": far * 100,
        "earlinessSeconds": median_lead,
        "earlinessScore": earliness * 100,
        "f1": f1 * 100,
        "precision": precision * 100,
        "tp": tp,
        "late": late,
        "miss": miss,
        "fp": fp,
        "wins": wins,
        "meanLeadSeconds": mean_lead,
    }


def _family_metrics(raw: Any, label: str, *, n_faulty: int) -> dict[str, dict[str, Any]]:
    families = _as_mapping(raw, label)
    parsed: dict[str, dict[str, Any]] = {}
    total = 0
    for family, raw_metrics in families.items():
        if not isinstance(family, str) or not family:
            raise FaultDetectionResultError(f"{label} contains an invalid family name")
        metrics = _as_mapping(raw_metrics, f"{label}.{family}")
        count = _as_int(metrics.get("n"), f"{label}.{family}.n")
        tp = _as_int(metrics.get("tp"), f"{label}.{family}.tp", maximum=count)
        recall = _as_number(
            metrics.get("recall"), f"{label}.{family}.recall", minimum=0, maximum=1
        )
        expected_recall = tp / count if count else 0.0
        if not math.isclose(recall, expected_recall, abs_tol=1e-9):
            raise FaultDetectionResultError(
                f"{label}.{family}.recall is inconsistent with tp"
            )
        total += count
        parsed[family] = {
            "family": family,
            "nFaulty": count,
            "recall": recall * 100,
            "tp": tp,
            # The result schema only reports early TP and total per family. It
            # cannot truthfully split the remaining cases into late vs missed.
            "late": None,
            "miss": None,
            "notEarly": count - tp,
        }
    if total != n_faulty:
        raise FaultDetectionResultError(f"{label} family counts do not add up")
    return parsed


def _ordered_names(values: set[str], preferred: tuple[str, ...]) -> list[str]:
    return [item for item in preferred if item in values] + sorted(values - set(preferred))


def _build_summary(
    leaderboard: Mapping[str, Any],
    analysis: Mapping[str, Any],
    *,
    snapshot_ns: int,
    station_count: int | None,
    station_analysis: list[dict[str, Any]],
) -> dict[str, Any]:
    n_faulty = _as_int(leaderboard.get("n_faulty"), "leaderboard.n_faulty")
    n_clean = _as_int(leaderboard.get("n_clean"), "leaderboard.n_clean")
    sessions = n_faulty + n_clean
    split = leaderboard.get("split")
    if not isinstance(split, str) or not split:
        raise FaultDetectionResultError("leaderboard.split must be a non-empty string")

    detectors = _as_mapping(leaderboard.get("detectors"), "leaderboard.detectors")
    _validate_detector_names(detectors, "leaderboard")
    wall_seconds = _as_mapping(leaderboard.get("wall_seconds"), "leaderboard.wall_seconds")
    _validate_detector_names(wall_seconds, "leaderboard.wall_seconds")

    overall = _as_mapping(analysis.get("overall"), "analysis.overall")
    analysis_faulty = _as_int(overall.get("n_faulty"), "analysis.overall.n_faulty")
    analysis_clean = _as_int(overall.get("n_clean"), "analysis.overall.n_clean")
    if (analysis_faulty, analysis_clean) != (n_faulty, n_clean):
        raise FaultDetectionResultError("analysis and leaderboard counts do not match")
    overall_detectors = _as_mapping(overall.get("detectors"), "analysis.overall.detectors")
    _validate_detector_names(overall_detectors, "analysis.overall")

    leaderboard_rows: list[dict[str, Any]] = []
    family_data_by_model: dict[str, dict[str, dict[str, Any]]] = {}
    for meta in _MODEL_META:
        raw_name = meta["raw"]
        metrics = _public_metrics(
            detectors[raw_name],
            f"leaderboard.detectors.{raw_name}",
            n_faulty=n_faulty,
            n_clean=n_clean,
        )
        # Validate the duplicate overall metrics and take family analysis from
        # analysis_test.json, which is the canonical analysis artifact.
        analysis_metrics = _public_metrics(
            overall_detectors[raw_name],
            f"analysis.overall.detectors.{raw_name}",
            n_faulty=n_faulty,
            n_clean=n_clean,
        )
        for key, value in metrics.items():
            analysis_value = analysis_metrics[key]
            if isinstance(value, float):
                matches = math.isclose(value, analysis_value, abs_tol=1e-9)
            else:
                matches = value == analysis_value
            if not matches:
                raise FaultDetectionResultError(
                    f"analysis and leaderboard metrics differ for {raw_name}.{key}"
                )
        family_data_by_model[raw_name] = _family_metrics(
            _as_mapping(overall_detectors[raw_name], raw_name).get("by_family"),
            f"analysis.overall.detectors.{raw_name}.by_family",
            n_faulty=n_faulty,
        )
        row = {key: value for key, value in meta.items() if key != "raw"}
        row.update(metrics)
        row["state"] = "complete"
        row["wallSeconds"] = _as_number(
            wall_seconds[raw_name], f"leaderboard.wall_seconds.{raw_name}", minimum=0
        )
        leaderboard_rows.append(row)

    leaderboard_rows.sort(key=lambda row: (-row["score"], row["name"]))
    for rank, row in enumerate(leaderboard_rows, start=1):
        row["rank"] = rank

    all_families = set().union(*(set(item) for item in family_data_by_model.values()))
    family_names = _ordered_names(all_families, _FAMILY_ORDER)
    for row in leaderboard_rows:
        raw_name = next(meta["raw"] for meta in _MODEL_META if meta["id"] == row["id"])
        model_families = family_data_by_model[raw_name]
        if set(model_families) != all_families:
            raise FaultDetectionResultError(
                f"analysis.overall.detectors.{raw_name} has an incomplete family set"
            )
        row["byFamily"] = [model_families[name] for name in family_names]

    by_source = _as_mapping(analysis.get("by_source"), "analysis.by_source")
    if not by_source:
        raise FaultDetectionResultError("analysis.by_source cannot be empty")
    source_rows: list[dict[str, Any]] = []
    source_faulty_total = 0
    source_clean_total = 0
    ranked_raw_names = [
        next(meta["raw"] for meta in _MODEL_META if meta["id"] == row["id"])
        for row in leaderboard_rows
    ]
    for source in _ordered_names(set(by_source), _SOURCE_ORDER):
        raw_source = _as_mapping(by_source[source], f"analysis.by_source.{source}")
        source_faulty = _as_int(
            raw_source.get("n_faulty"), f"analysis.by_source.{source}.n_faulty"
        )
        source_clean = _as_int(
            raw_source.get("n_clean"), f"analysis.by_source.{source}.n_clean"
        )
        source_detectors = _as_mapping(
            raw_source.get("detectors"), f"analysis.by_source.{source}.detectors"
        )
        _validate_detector_names(source_detectors, f"analysis.by_source.{source}")
        source_metrics: list[dict[str, Any]] = []
        for raw_name in ranked_raw_names:
            meta = _META_BY_RAW[raw_name]
            public = _public_metrics(
                source_detectors[raw_name],
                f"analysis.by_source.{source}.detectors.{raw_name}",
                n_faulty=source_faulty,
                n_clean=source_clean,
            )
            source_metrics.append({"id": meta["id"], "name": meta["name"], **public})
        source_rows.append(
            {
                "source": source,
                "nFaulty": source_faulty,
                "nClean": source_clean,
                "sessions": source_faulty + source_clean,
                "detectors": source_metrics,
            }
        )
        source_faulty_total += source_faulty
        source_clean_total += source_clean
    if (source_faulty_total, source_clean_total) != (n_faulty, n_clean):
        raise FaultDetectionResultError("analysis.by_source counts do not add up")

    station_totals = {
        key: sum(row[key] for row in station_analysis)
        for key in ("sessions", "faultySessions", "normalSessions", "tp", "late", "miss", "fp")
    }
    agentic = next(row for row in leaderboard_rows if row["id"] == "agentic-ai")
    expected_station_totals = {
        "sessions": sessions,
        "faultySessions": n_faulty,
        "normalSessions": n_clean,
        "tp": agentic["tp"],
        "late": agentic["late"],
        "miss": agentic["miss"],
        "fp": agentic["fp"],
    }
    if station_totals != expected_station_totals:
        raise FaultDetectionResultError(
            "per-station AgenticAI counts do not match the verified overall result"
        )

    snapshot = datetime.fromtimestamp(snapshot_ns / 1_000_000_000, timezone.utc)
    return {
        "source": "full_fleet",
        "snapshotAt": snapshot.isoformat().replace("+00:00", "Z"),
        "run": {
            "status": "complete",
            "stage": "analyze",
            "progress": 100,
            "processed": sessions,
            "remaining": 0,
            "total": sessions,
            "etaHours": [0, 0],
        },
        "dataset": {
            "sessions": sessions,
            "faultySessions": n_faulty,
            "normalSessions": n_clean,
            "stations": station_count,
            "split": split,
        },
        "pipeline": [
            {"id": stage_id, "label": label, "state": "complete", "progress": 100}
            for stage_id, label in _PIPELINE
        ],
        "leaderboard": leaderboard_rows,
        "analysis": {
            "bySource": source_rows,
            "byStation": station_analysis,
            "faultFamilies": family_names,
        },
    }


def _load_train_station_analysis(
    train_records: Path,
    split_data: Mapping[str, Any] | None,
    held_out: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bytes]:
    """Per-station rows for the training stations, from an in-sample replay.

    They never enter the held-out gates, totals or leaderboard; they are only
    attached as analysis.byStationTrain for the station views.
    """
    records, raw, _ = _read_records(train_records, _MAX_TRAIN_RECORDS_BYTES)
    rows = _build_station_analysis(records, split_name="train", source_label=train_records.name)
    names = {row["station"] for row in rows}
    overlap = names & {row["station"] for row in held_out}
    if overlap:
        raise FaultDetectionResultError(
            f"{train_records.name} contains held-out stations: {sorted(overlap)[:3]}"
        )
    if split_data is not None:
        expected = split_data.get("train")
        if isinstance(expected, list) and set(expected) != names:
            raise FaultDetectionResultError(
                f"{train_records.name} stations do not match {_SPLIT_FILE}.train"
            )
    # the leaderboard written by the same replay (records_<tag>.json ->
    # leaderboard_<tag>.json) must exist and agree with the station rows
    name = train_records.name
    if not (name.startswith("records_") and name.endswith(".json")):
        raise FaultDetectionResultError(f"{name} is not a records_<tag>.json file")
    candidate = train_records.with_name("leaderboard_" + name[len("records_"):])
    if not candidate.is_file():
        raise FaultDetectionResultError(f"{candidate.name} is missing next to {name}")
    board, _, _ = _read_result(candidate)
    if board.get("split") != "train":
        raise FaultDetectionResultError(f"{candidate.name} is not a train-split leaderboard")
    agentic = (board.get("detectors") or {}).get("AgenticAI")
    if not isinstance(agentic, Mapping):
        raise FaultDetectionResultError(f"{candidate.name} has no AgenticAI result")
    totals = {key: sum(row[key] for row in rows) for key in ("faultySessions", "normalSessions", "tp", "late", "miss", "fp")}
    expected_totals = {
        "faultySessions": board.get("n_faulty"),
        "normalSessions": board.get("n_clean"),
        "tp": agentic.get("tp"),
        "late": agentic.get("late"),
        "miss": agentic.get("miss"),
        "fp": agentic.get("fp"),
    }
    if totals != expected_totals:
        raise FaultDetectionResultError(
            f"{train_records.name} station rows do not match {candidate.name}"
        )
    return rows, raw


def load_fault_detection_summary(
    data_root: str | Path | None = None,
    *,
    train_records: str | Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Load, validate, and transform the two fixed full-fleet result files.

    `train_records` optionally adds the in-sample training-station rows as
    analysis.byStationTrain (desktop builds); the held-out summary is unchanged.
    """
    root = Path(
        data_root
        if data_root is not None
        else os.getenv("EV_CHARGER_AI_DATA_ROOT", str(_DEFAULT_DATA_ROOT))
    )
    leaderboard, leaderboard_raw, leaderboard_ns = _read_result(
        root / _RESULTS_DIR / _LEADERBOARD_FILE
    )
    analysis, analysis_raw, analysis_ns = _read_result(
        root / _RESULTS_DIR / _ANALYSIS_FILE
    )
    records, records_raw, records_ns = _read_records(
        root / _RESULTS_DIR / _RECORDS_FILE
    )
    station_analysis = _build_station_analysis(records)
    station_count: int | None = None
    split_raw = b""
    split_data: Mapping[str, Any] | None = None
    split_path = root / _SPLIT_FILE
    if split_path.is_file():
        split_data, split_raw, _ = _read_result(split_path)
        split_name = leaderboard.get("split")
        stations = split_data.get(split_name) if isinstance(split_name, str) else None
        if not isinstance(stations, list) or any(
            not isinstance(station, str) or not station for station in stations
        ):
            raise FaultDetectionResultError(
                f"{_SPLIT_FILE}.{split_name} must be a list of station names"
            )
        if len(stations) != len(set(stations)):
            raise FaultDetectionResultError(f"{_SPLIT_FILE}.{split_name} contains duplicates")
        station_count = len(stations)
        if {row["station"] for row in station_analysis} != set(stations):
            raise FaultDetectionResultError(
                f"{_RECORDS_FILE} stations do not match {_SPLIT_FILE}.{split_name}"
            )

    train_rows: list[dict[str, Any]] | None = None
    train_raw = b""
    if train_records is not None:
        train_rows, train_raw = _load_train_station_analysis(
            Path(train_records), split_data, station_analysis
        )

    digest = hashlib.sha256(
        leaderboard_raw
        + b"\0"
        + analysis_raw
        + b"\0"
        + records_raw
        + b"\0"
        + split_raw
        + b"\0"
        + train_raw
    ).hexdigest()
    etag = f'"{digest}"'
    summary = _build_summary(
        leaderboard,
        analysis,
        # the benchmark date is the held-out result's; the in-sample file must
        # not move the "data as of" the dashboard shows
        snapshot_ns=max(leaderboard_ns, analysis_ns, records_ns),
        station_count=station_count,
        station_analysis=station_analysis,
    )
    if train_rows is not None:
        summary["analysis"]["byStationTrain"] = train_rows
    return summary, etag


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    target = etag.removeprefix("W/")
    for candidate in header.split(","):
        value = candidate.strip()
        if value == "*" or value.removeprefix("W/") == target:
            return True
    return False


def get_pcap_job_service() -> PcapJobService:
    global _JOB_SERVICE
    if _JOB_SERVICE is None:
        project_root = Path(__file__).resolve().parents[2]
        jobs_root = (
            Path(os.environ.get("LOCALAPPDATA", str(project_root)))
            / "iMPS-FaultDetection"
            / "jobs"
            / "backend"
        )
        _JOB_SERVICE = PcapJobService(
            project_root=project_root,
            data_root=Path(os.environ.get("EV_CHARGER_AI_DATA_ROOT", _DEFAULT_DATA_ROOT)),
            ai_project=Path(
                os.environ.get(
                    "FAULT_DETECTION_AI_PROJECT",
                    r"F:\pcap_downloads\ev_charger_ai_v4_original_snapshot",
                )
            ),
            python_executable=Path(
                os.environ.get(
                    "FAULT_DETECTION_AI_PYTHON",
                    r"C:\Users\user1\anaconda3\envs\ev_ai\python.exe",
                )
            ),
            jobs_root=jobs_root,
        )
    return _JOB_SERVICE


def _job_owner(current: UserClaims) -> str:
    return str(current.user_id or current.sub)


def _raise_job_http_error(exc: JobServiceError) -> None:
    raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("/summary")
def get_fault_detection_summary(
    request: Request,
    _current: UserClaims = Depends(get_current_user),
):
    try:
        summary, etag = load_fault_detection_summary()
    except FaultDetectionResultError as exc:
        log.warning("Fault-detection result unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Full-fleet benchmark results are unavailable or invalid",
        ) from exc

    cache_control = "private, max-age=60, stale-while-revalidate=300"
    headers = {
        "ETag": etag,
        "Cache-Control": cache_control,
        "Vary": "Cookie, Authorization",
    }
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=summary, headers=headers)


@router.post("/jobs", status_code=202)
async def create_fault_detection_job(
    request: Request,
    current: UserClaims = Depends(get_current_user),
):
    if request.headers.get("content-encoding"):
        raise HTTPException(status_code=415, detail="Compressed request bodies are not supported")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/octet-stream":
        raise HTTPException(status_code=415, detail="Expected application/octet-stream")
    encoded_filename = request.headers.get("x-filename", "")
    try:
        filename = unquote(encoded_filename, encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid X-Filename header") from exc
    content_length_header = request.headers.get("content-length")
    try:
        content_length = int(content_length_header) if content_length_header else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc

    service = get_pcap_job_service()
    upload = None
    try:
        upload = service.begin_upload(
            filename,
            content_length=content_length,
            owner=_job_owner(current),
        )
        async for chunk in request.stream():
            service.write_upload(upload, chunk)
        job = service.finish_upload(upload)
    except JobServiceError as exc:
        if upload is not None and not upload.closed:
            service.abort_upload(upload)
        _raise_job_http_error(exc)
    except Exception:
        if upload is not None and not upload.closed:
            service.abort_upload(upload)
        log.exception("Unable to accept PCAP analysis upload")
        raise HTTPException(status_code=500, detail="Unable to accept the PCAP upload")
    return JSONResponse(
        content=job,
        status_code=202,
        headers={
            "Location": f"/ai/fault-detection/jobs/{job['jobId']}",
            "Retry-After": "1",
            "Cache-Control": "no-store",
        },
    )


@router.get("/jobs/{job_id}")
def get_fault_detection_job(
    job_id: str,
    current: UserClaims = Depends(get_current_user),
):
    try:
        job = get_pcap_job_service().get_job(job_id, owner=_job_owner(current))
    except JobServiceError as exc:
        _raise_job_http_error(exc)
    return JSONResponse(content=job, headers={"Cache-Control": "no-store"})

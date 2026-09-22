"""Run the verified AgenticAI detector against one uploaded PCAP.

This worker is intentionally executed in the dedicated ``ev_ai`` conda
environment.  It reads only the trusted full-fleet model artifacts and writes
all extraction output inside the caller-provided job directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


THREAD_ENV = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
FLOAT_FIELDS = (
    "soc",
    "evse_v",
    "evse_i",
    "ev_target_v",
    "ev_target_i",
    "ev_max_v",
    "ev_max_i",
    "evse_max_v",
    "evse_max_i",
    "remaining_full_min",
    "remaining_bulk_min",
)
TEXT_FIELDS = (
    "session",
    "resp_code",
    "evse_status",
    "isolation",
    "notification",
    "ev_err",
    "ev_ready",
    "charge_complete",
    "bulk_complete",
    "evse_processing",
    "limit_achieved",
    "validation",
)
OPENING_MESSAGES = {
    "supportedAppProtocolReq",
    "supportedAppProtocolRes",
    "SessionSetupReq",
}
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def update_progress(path: Path, stage: str, progress: float, detail: str) -> None:
    write_json_atomic(
        path,
        {
            "stage": stage,
            "progress": max(0.0, min(100.0, float(progress))),
            "detail": detail,
            "updatedAt": utc_now(),
        },
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_version(artifacts: Path) -> str:
    digest = hashlib.sha256()
    for name in ("lstm_ae.pt", "gru_fore.pt"):
        path = artifacts / name
        if not path.is_file():
            raise RuntimeError(f"Trusted model artifact is missing: {path}")
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
            values["extra"] = json.loads(extra)
        except (TypeError, json.JSONDecodeError):
            values["extra"] = {}
    return event_class(**values)


def severity_for(confidence: float) -> str:
    if confidence >= 0.95:
        return "critical"
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.70:
        return "medium"
    return "low"


def _truthy_protocol_value(value: Any) -> bool:
    return str(value or "").strip().upper() in {"TRUE", "1", "YES"}


def _row_extra(row: dict[str, Any]) -> dict[str, Any]:
    extra = row.get("extra")
    if isinstance(extra, dict):
        return extra
    if isinstance(extra, str) and extra:
        try:
            decoded = json.loads(extra)
            return decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def analyze_stop_attribution(
    rows: list[dict[str, Any]],
    alert: dict[str, Any] | None,
) -> dict[str, Any]:
    """Separate the observed stop request from the likely stop trigger.

    DIN 70121 SessionStopReq is sent by the EVCC, but that does not mean the
    vehicle caused every stop: the EVSE may have requested it earlier through
    EVSENotification.  TCP direction is not retained by the extractor, so RST
    attribution must remain unknown.
    """
    v2g_rows = [row for row in rows if row.get("kind") == "v2g"]
    stop_request = next(
        (row for row in v2g_rows if row.get("msg") == "SessionStopReq"), None
    )
    request_sender = "vehicle" if stop_request is not None else None
    family = str((alert or {}).get("faultFamily") or "").upper()
    reason = str((alert or {}).get("reason") or "")

    evse_trigger = next(
        (
            row
            for row in v2g_rows
            if str(row.get("notification") or "").lower() in {"stopcharging", "terminate"}
            or row.get("evse_status")
            in {"EVSE_Malfunction", "EVSE_EmergencyShutdown"}
        ),
        None,
    )
    ev_trigger = next(
        (
            row
            for row in v2g_rows
            if _truthy_protocol_value(row.get("charge_complete"))
            or str(row.get("ev_err") or "").upper() not in {"", "NO_ERROR", "NODATA"}
            or str(_row_extra(row).get("ChargeProgress") or "").lower()
            == "stop"
        ),
        None,
    )
    failed_row = next(
        (
            row
            for row in v2g_rows
            if str(row.get("resp_code") or "").upper().startswith("FAILED")
        ),
        None,
    )
    tcp_reset = any(
        row.get("kind") == "tcp" and row.get("msg") == "RST" for row in rows
    )
    has_v2g = bool(v2g_rows)

    if family == "SLAC_FAILURE" or (not has_v2g and any(row.get("kind") == "hpav" for row in rows)):
        return {
            "triggeredBy": "not_applicable",
            "requestSender": None,
            "confidence": "high",
            "evidence": "SLAC/PLC matching did not establish a V2G charging session.",
        }
    if evse_trigger is not None:
        status = evse_trigger.get("evse_status") or evse_trigger.get("notification")
        return {
            "triggeredBy": "charger",
            "requestSender": request_sender,
            "confidence": "high",
            "evidence": f"EVSE reported {status} before or during session close.",
        }
    if family == "ISOLATION_FAULT":
        return {
            "triggeredBy": "charger",
            "requestSender": request_sender,
            "confidence": "high",
            "evidence": "EVSE reported EVSEIsolationStatus=Fault and inhibited power for safety.",
        }
    if ev_trigger is not None:
        marker = (
            ev_trigger.get("ev_err")
            or ("ChargingComplete=TRUE" if _truthy_protocol_value(ev_trigger.get("charge_complete")) else None)
            or f"ChargeProgress={_row_extra(ev_trigger).get('ChargeProgress')}"
        )
        return {
            "triggeredBy": "vehicle",
            "requestSender": request_sender,
            "confidence": "high" if ev_trigger.get("ev_err") else "medium",
            "evidence": f"EV/EVCC reported {marker}.",
        }
    if family == "PROTOCOL_FAILED" and failed_row is not None:
        response = failed_row.get("resp_code")
        message = failed_row.get("msg") or "response"
        if message == "SessionStopRes" and request_sender == "vehicle":
            return {
                "triggeredBy": "vehicle",
                "requestSender": "vehicle",
                "confidence": "high",
                "evidence": f"EV sent SessionStopReq; EVSE then returned {message}:{response}.",
            }
        return {
            "triggeredBy": "charger",
            "requestSender": request_sender,
            "confidence": "high",
            "evidence": f"EVSE returned {message}:{response}.",
        }
    if "no SessionSetupRes" in reason:
        return {
            "triggeredBy": "charger",
            "requestSender": request_sender,
            "confidence": "medium",
            "evidence": "EV sent session setup traffic but no SessionSetupRes was observed from the EVSE.",
        }
    if family in {"COMM_FREEZE", "SESSION_ABORT"} and "no further request" in reason:
        return {
            "triggeredBy": "vehicle",
            "requestSender": request_sender,
            "confidence": "medium",
            "evidence": "The EV sent no next request before the protocol timeout.",
        }
    if family in {"COMM_FREEZE", "SESSION_ABORT"} and (
        "EVSEProcessing" in reason or "CableCheck" in reason
    ):
        return {
            "triggeredBy": "charger",
            "requestSender": request_sender,
            "confidence": "medium",
            "evidence": "EVSE processing did not complete before the applicable phase timeout.",
        }
    if tcp_reset:
        return {
            "triggeredBy": "unknown",
            "requestSender": request_sender,
            "confidence": "low",
            "evidence": "TCP RST was observed, but the extractor does not retain endpoint direction.",
        }
    if "re-slac" in reason.lower() or "link" in reason.lower():
        return {
            "triggeredBy": "communication",
            "requestSender": request_sender,
            "confidence": "medium",
            "evidence": "PLC/V2G link degradation was observed; the failing endpoint is not identifiable.",
        }
    if request_sender == "vehicle":
        return {
            "triggeredBy": "vehicle",
            "requestSender": "vehicle",
            "confidence": "medium",
            "evidence": "SessionStopReq from the EV was observed with no earlier EVSE stop marker in the capture.",
        }
    return {
        "triggeredBy": "unknown",
        "requestSender": None,
        "confidence": "low",
        "evidence": "The available packet fields do not identify which side initiated the stop.",
    }


def capture_format(path: Path) -> str:
    with path.open("rb") as handle:
        magic = handle.read(4)
    return "pcapng" if magic == b"\x0a\x0d\x0d\x0a" else "pcap"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--ai-project", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--original-name", required=True)
    parser.add_argument("--sha256", default="")
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    input_path = args.input.resolve(strict=True)
    ai_project = args.ai_project.resolve(strict=True)
    data_root = args.data_root.resolve(strict=True)
    artifacts = data_root / "artifacts"
    telemetry_path = args.output.parent / "telemetry.csv"

    for name in THREAD_ENV:
        os.environ[name] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["EV_AI_DATA"] = str(data_root)
    os.environ["EV_AI_ARTIFACTS"] = str(artifacts)
    os.environ["EV_AI_ISO"] = "0"
    os.environ["EV_AI_ISO_VEC"] = "0"
    sys.path.insert(0, str(ai_project))

    update_progress(args.progress, "extracting", 12, "Decoding PCAP with TShark")
    from pipeline.extract_worker import extract

    extracted_events = int(extract(str(input_path), str(telemetry_path)))
    update_progress(
        args.progress,
        "sessionizing",
        42,
        f"Reconstructing sessions from {extracted_events:,} relevant events",
    )
    from pipeline.sessionize import iter_sessions

    warnings: list[dict[str, str]] = []
    if extracted_events == 0:
        warnings.append(
            {
                "code": "no_supported_events",
                "message": (
                    "No supported DIN 70121 / ISO 15118, SLAC, or diagnostic "
                    "TCP events were decoded from this capture."
                ),
            }
        )
    detector = None
    model_version = artifact_version(artifacts)
    if extracted_events:
        update_progress(args.progress, "loading_model", 55, "Loading verified Agentic AI artifacts")
        from core.feature_tracker import FeatureTracker
        from core.schema import Event
        from models.agentic_ai import AgenticAI

        detector = AgenticAI()
    else:
        FeatureTracker = Event = None  # type: ignore[assignment,misc]

    session_results: list[dict[str, Any]] = []
    primary_alert: dict[str, Any] | None = None
    complete_sessions = 0
    alerted_sessions = 0
    incomplete_sessions = 0
    session_count = 0
    processed_session_events = 0
    capture_start = None
    capture_end = None
    max_session_details = 500
    for index, rows in enumerate(iter_sessions(telemetry_rows(telemetry_path))):
        assert detector is not None and FeatureTracker is not None and Event is not None
        session_count += 1
        tracker = FeatureTracker()
        detector.reset("uploaded_capture", "connector1")
        first_alert = None
        first_message = None
        last_message = None
        t_start = float(rows[0]["t"]) if rows else None
        t_end = float(rows[-1]["t"]) if rows else None
        for row in rows:
            event = row_to_event(row, Event)
            if event.kind == "v2g" and event.msg:
                if first_message is None:
                    first_message = event.msg
                last_message = event.msg
            state = tracker.update(event)
            alerts = detector.observe(event, state)
            if alerts and first_alert is None:
                alert = alerts[0]
                first_alert = {
                    "timestamp": float(alert.t),
                    "t": float(alert.t),
                    "offsetSeconds": max(0.0, float(alert.t) - float(t_start or alert.t)),
                    "confidence": max(0.0, min(1.0, float(alert.confidence))),
                    "reason": str(alert.reason),
                    "faultFamily": str(alert.fault_guess) or None,
                    "faultGuess": str(alert.fault_guess) or None,
                }
                if primary_alert is None or first_alert["timestamp"] < primary_alert["timestamp"]:
                    primary_alert = first_alert
        detector.end_session("uploaded_capture", "connector1")

        stop_analysis = analyze_stop_attribution(rows, first_alert)
        if first_alert is not None:
            first_alert["stopAnalysis"] = stop_analysis

        graceful = any(
            row.get("kind") == "v2g"
            and row.get("msg") == "SessionStopRes"
            and not str(row.get("resp_code") or "").upper().startswith("FAILED")
            for row in rows
        )
        if graceful:
            complete_sessions += 1
        else:
            incomplete_sessions += 1
        if first_alert is not None:
            alerted_sessions += 1
        if index == 0 and first_message and first_message not in OPENING_MESSAGES:
            warnings.append(
                {
                    "code": "capture_starts_mid_session",
                    "message": "The first decoded charging dialog starts mid-session; earlier evidence may be missing.",
                }
            )
        if t_start is not None:
            capture_start = t_start if capture_start is None else min(capture_start, t_start)
        if t_end is not None:
            capture_end = t_end if capture_end is None else max(capture_end, t_end)
        if len(session_results) < max_session_details:
            session_results.append(
                {
                    "index": index + 1,
                    "eventCount": len(rows),
                    "tStart": t_start,
                    "tEnd": t_end,
                    "durationSeconds": max(0.0, (t_end or 0.0) - (t_start or 0.0)),
                    "gracefulClose": graceful,
                    "firstMessage": first_message,
                    "lastMessage": last_message,
                    "alert": first_alert,
                    "stopAnalysis": stop_analysis,
                }
            )
        processed_session_events += len(rows)
        update_progress(
            args.progress,
            "inferencing",
            58 + 35 * min(1.0, processed_session_events / max(1, extracted_events)),
            f"Analyzed {session_count:,} reconstructed session(s)",
        )

    if extracted_events > 0 and session_count == 0:
        warnings.append(
            {
                "code": "no_sessions",
                "message": "Relevant packets were found, but no charging session could be reconstructed.",
            }
        )
    if incomplete_sessions:
        warnings.append(
            {
                "code": "incomplete_session",
                "message": (
                    f"{incomplete_sessions:,} reconstructed session(s) have no observed "
                    "SessionStop handshake and may be truncated."
                ),
            }
        )
    if session_count > max_session_details:
        warnings.append(
            {
                "code": "session_details_truncated",
                "message": (
                    f"Session detail rows are limited to the first {max_session_details:,}; "
                    f"all {session_count:,} sessions were still evaluated."
                ),
            }
        )

    if primary_alert is not None:
        confidence = float(primary_alert["confidence"])
        verdict = {
            "status": "fault_detected",
            "faultDetected": True,
            "faultFamily": primary_alert["faultFamily"],
            "confidence": confidence,
            "reason": primary_alert["reason"],
            "severity": severity_for(confidence),
            "stopAnalysis": primary_alert.get("stopAnalysis"),
        }
    elif session_count == 0 or complete_sessions < session_count:
        verdict = {
            "status": "inconclusive",
            "faultDetected": None,
            "faultFamily": None,
            "confidence": None,
            "reason": "The capture does not contain enough complete, supported session evidence for a definitive result.",
            "severity": None,
            "stopAnalysis": None,
        }
    else:
        verdict = {
            "status": "no_fault_detected",
            "faultDetected": False,
            "faultFamily": None,
            "confidence": None,
            "reason": "Agentic AI did not emit a fault alert in the complete sessions present in this capture.",
            "severity": None,
            "stopAnalysis": None,
        }
        warnings.append(
            {
                "code": "no_alert_not_health_proof",
                "message": "No alert is not a guarantee that the charger is healthy; only captured protocol evidence was evaluated.",
            }
        )

    digest = args.sha256.lower() or sha256_file(input_path)
    update_progress(args.progress, "finalizing", 97, "Writing the analysis result")
    return {
        "schemaVersion": 1,
        "file": {
            "originalName": args.original_name,
            "sizeBytes": input_path.stat().st_size,
            "sha256": digest,
            "captureFormat": capture_format(input_path),
        },
        "model": {
            "id": "agentic-ai",
            "name": "Agentic AI",
            "benchmarkRank": 1,
            "artifactVersion": model_version,
            "coldStart": True,
        },
        "capture": {
            "extractedEvents": extracted_events,
            "sessionCount": session_count,
            "alertedSessions": alerted_sessions,
            "completeSessions": complete_sessions,
            "tStart": capture_start,
            "tEnd": capture_end,
            "durationSeconds": max(0.0, (capture_end or 0.0) - (capture_start or 0.0)),
        },
        "verdict": verdict,
        "sessions": session_results,
        "warnings": warnings,
        "processing": {
            "durationSeconds": max(0.0, time.perf_counter() - started),
            "completedAt": utc_now(),
        },
    }


def main() -> int:
    args = parse_args()
    try:
        result = run(args)
        write_json_atomic(args.output, result)
        update_progress(args.progress, "complete", 100, "Analysis complete")
        print(
            json.dumps(
                {
                    "status": result["verdict"]["status"],
                    "sessions": result["capture"]["sessionCount"],
                    "events": result["capture"]["extractedEvents"],
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 0
    except Exception as exc:
        try:
            update_progress(args.progress, "failed", 100, str(exc)[:400])
        except Exception:
            pass
        raise


if __name__ == "__main__":
    raise SystemExit(main())

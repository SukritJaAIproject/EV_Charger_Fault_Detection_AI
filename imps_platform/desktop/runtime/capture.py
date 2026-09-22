
"""Extract structured charging telemetry from one EV charger pcap via tshark.

The pcaps contain DIN 70121 (V2G) EXI messages decoded by the Wireshark V2G Lua
dissector, HomePlug AV (SLAC / Qualcomm Atheros link status) frames, and TCP.
Output: one CSV row per relevant event, flat columns + JSON extras.
Stdlib only, so it runs under any Python while the ML env is being built.
"""
import csv
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

FIELDS = [
    "frame.time_epoch",
    "tcp.stream",
    "tcp.flags.reset",
    "tcp.analysis.retransmission",
    "tcp.analysis.lost_segment",
    "v2gmsg.msgname",
    "v2gmsg.xml",
    "v2gmsg.validation",
    "_ws.col.info",
]

DISPLAY_FILTER = (
    "v2gmsg or v2gsdp-req or v2gsdp-res or homeplug-av "
    "or tcp.analysis.flags or tcp.flags.reset==1"
)

COLUMNS = [
    "t", "kind", "msg", "session", "resp_code", "evse_status", "isolation",
    "notification", "ev_err", "soc", "evse_v", "evse_i", "ev_target_v",
    "ev_target_i", "ev_max_v", "ev_max_i", "evse_max_v", "evse_max_i",
    "remaining_full_min", "remaining_bulk_min", "ev_ready", "charge_complete",
    "bulk_complete", "evse_processing", "limit_achieved", "validation",
    "tcp_stream", "extra",
]

NS_STRIP = re.compile(r"\{[^}]*\}")

# HomePlug info-line categories worth keeping as individual events
HPAV_KEEP = re.compile(
    r"SLAC|ATTEN_CHAR|SET_KEY|GET_KEY|VALIDATE|NW_INFO|NW_STATS|STA_CAP|"
    r"AMP_MAP|LINK_STATUS|SW_VER|Broadcom|Qualcomm",
    re.IGNORECASE,
)


def phys(elem):
    """PhysicalValueType {Multiplier, Unit, Value} -> float."""
    mult = val = None
    for ch in elem:
        tag = NS_STRIP.sub("", ch.tag)
        if tag == "Multiplier":
            mult = int(ch.text)
        elif tag == "Value":
            val = int(ch.text)
    if val is None:
        return None
    return val * (10 ** (mult or 0))


def walk(root):
    """Flatten XML tree to {tag: element} for the tags we care about (first hit)."""
    out = {}
    for elem in root.iter():
        tag = NS_STRIP.sub("", elem.tag)
        if tag not in out:
            out[tag] = elem
    return out


PHYS_MAP = {
    "EVSEPresentVoltage": "evse_v",
    "EVSEPresentCurrent": "evse_i",
    "EVTargetVoltage": "ev_target_v",
    "EVTargetCurrent": "ev_target_i",
    "EVMaximumVoltageLimit": "ev_max_v",
    "EVMaximumCurrentLimit": "ev_max_i",
    "EVSEMaximumVoltageLimit": "evse_max_v",
    "EVSEMaximumCurrentLimit": "evse_max_i",
    "RemainingTimeToFullSoC": "remaining_full_min",
    "RemainingTimeToBulkSoC": "remaining_bulk_min",
}

TEXT_MAP = {
    "ResponseCode": "resp_code",
    "EVSEStatusCode": "evse_status",
    "EVSEIsolationStatus": "isolation",
    "EVSENotification": "notification",
    "EVErrorCode": "ev_err",
    "EVRESSSOC": "soc",
    "EVReady": "ev_ready",
    "ChargingComplete": "charge_complete",
    "BulkChargingComplete": "bulk_complete",
    "EVSEProcessing": "evse_processing",
}

# Less common but diagnostic fields go into `extra`
EXTRA_TAGS = [
    "EVCCID", "EVSEID", "ServiceCategory", "ChargeProgress", "ChargingSession",
    "ReadyToChargeState", "FaultCode", "FaultMsg", "EVSEVoltageLimitAchieved",
    "EVSECurrentLimitAchieved", "EVSEPowerLimitAchieved", "ProtocolNamespace",
    "SchemaID", "ResponseCode", "DepartureTime", "EAmount", "FullSOC", "BulkSOC",
    "EVSEMinimumVoltageLimit", "EVSEMinimumCurrentLimit",
    "EVSEPeakCurrentRipple", "EVSEEnergyToBeDelivered",
]


def parse_v2g_row(msg, xml_text, row):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        row["extra"] = json.dumps({"xml_parse_error": True})
        return row
    tags = walk(root)
    if "SessionID" in tags and tags["SessionID"].text:
        row["session"] = tags["SessionID"].text
    for tag, col in TEXT_MAP.items():
        if tag in tags and tags[tag].text is not None:
            row[col] = tags[tag].text.strip()
    for tag, col in PHYS_MAP.items():
        if tag in tags:
            v = phys(tags[tag])
            if v is not None:
                row[col] = v
    lim = []
    for t in ("EVSEVoltageLimitAchieved", "EVSECurrentLimitAchieved",
              "EVSEPowerLimitAchieved"):
        if t in tags and tags[t].text == "true":
            lim.append(t[4].lower())  # v / c / p
    if lim:
        row["limit_achieved"] = "".join(lim)
    extra = {}
    for tag in EXTRA_TAGS:
        if tag in tags and tags[tag].text is not None and tag not in TEXT_MAP:
            extra[tag] = tags[tag].text.strip()
    if extra:
        row["extra"] = json.dumps(extra, separators=(",", ":"))
    return row


def extract(pcap_path, out_path, tshark_path):
    """Decode one capture with the explicitly supplied portable TShark."""
    cmd = [str(tshark_path), "-r", pcap_path, "-n", "-T", "fields", "-E", "occurrence=f"]
    for f in FIELDS:
        cmd += ["-e", f]
    cmd += ["-Y", DISPLAY_FILTER]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", bufsize=1 << 20,
    )
    tmp_path = out_path + ".tmp"
    n_rows = 0
    first_t = last_t = None   # packet-time span, for the ring-order manifest
    with open(tmp_path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        wr.writeheader()
        for line in proc.stdout:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < len(FIELDS):
                parts += [""] * (len(FIELDS) - len(parts))
            (t, tcp_stream, tcp_rst, tcp_rex, tcp_lost,
             msgname, xml_text, validation, info) = parts[: len(FIELDS)]
            row = {"t": t, "tcp_stream": tcp_stream}
            if msgname:
                row["kind"] = "v2g"
                row["msg"] = msgname
                if validation:
                    row["validation"] = validation
                row = parse_v2g_row(msgname, xml_text, row)
            elif info.startswith("V2G") or "SECC Discovery" in info:
                row["kind"] = "sdp"
                row["msg"] = info[:80]
            elif tcp_rst == "True" or tcp_rex != "" or tcp_lost != "":
                # NB: tcp.analysis.* are FT_NONE fields — tshark prints "1"
                # when present, "" when absent (only tcp.flags.reset is a
                # real boolean printing True/False)
                row["kind"] = "tcp"
                row["msg"] = (
                    "RST" if tcp_rst == "True"
                    else ("RETX" if tcp_rex != "" else "LOST")
                )
            else:
                # HomePlug AV frame — keep only diagnostically interesting ones
                m = HPAV_KEEP.search(info)
                if not m:
                    continue
                row["kind"] = "hpav"
                # strip vendor prefix noise: "Qualcomm Atheros, LINK_STATUS.REQ"
                row["msg"] = info.split(", ", 1)[-1][:80]
            wr.writerow(row)
            n_rows += 1
            if t:
                if first_t is None:
                    first_t = t
                last_t = t
    rc = proc.wait()
    if rc not in (0, 2):  # 2 = tshark warning (e.g. cut short) but output usable
        os.remove(tmp_path)
        raise RuntimeError(f"tshark rc={rc} for {pcap_path}")
    os.replace(tmp_path, out_path)
    # sidecar so the manifest step never has to re-read 100+ GB of CSV
    meta = {"rows": n_rows,
            "first": float(first_t) if first_t is not None else None,
            "last": float(last_t) if last_t is not None else None}
    with open(out_path[:-4] + ".meta.json", "w") as fh:
        json.dump(meta, fh)
    return n_rows


IDLE_GAP_S = 60.0
ACTIVITY_KINDS = {"v2g", "sdp", "tcp"}
SLAC_ACTIVITY = ("SLAC", "ATTEN_CHAR", "SET_KEY", "VALIDATE")


def _is_activity(row):
    if row["kind"] in ACTIVITY_KINDS:
        return True
    return row["kind"] == "hpav" and any(
        marker in row["msg"] for marker in SLAC_ACTIVITY
    )


def iter_sessions(rows):
    """Yield charging-session row lists using the published fleet splitter."""
    current = []
    last_activity_t = None
    session_open = False
    pending_quiet = []
    seen_close = False

    for row in rows:
        active = _is_activity(row)
        if not session_open:
            if active:
                session_open = True
                seen_close = False
                current = [
                    quiet
                    for quiet in pending_quiet
                    if row["t"] - quiet["t"] <= 10.0
                ]
                current.append(row)
                pending_quiet = []
                last_activity_t = row["t"]
                if row["msg"] in ("SessionStopRes", "SessionStopReq"):
                    seen_close = True
            else:
                pending_quiet.append(row)
                if len(pending_quiet) > 200:
                    pending_quiet = pending_quiet[-100:]
            continue

        gap = row["t"] - last_activity_t
        if active:
            if gap > IDLE_GAP_S:
                if current:
                    yield current
                current = [row]
                seen_close = False
            else:
                if (
                    row["msg"] in ("supportedAppProtocolReq", "SessionSetupReq")
                    and current
                    and seen_close
                ):
                    yield current
                    current = []
                    seen_close = False
                current.append(row)
            last_activity_t = row["t"]
            if row["msg"] in ("SessionStopRes", "SessionStopReq"):
                seen_close = True
        elif gap > IDLE_GAP_S:
            if current:
                yield current
            current = []
            session_open = False
            seen_close = False
            pending_quiet = [row]
        else:
            current.append(row)

    if session_open and current:
        yield current

"""Archive and summarize the completed public-source ISO 15118-3 research.

The Claude workflow output is a JSON file produced by the 93-agent sweep and
verification run.  This exporter turns that ephemeral file into two durable
project artifacts:

* results/iso15118_3_public_sources.json -- full machine-readable evidence
* docs/iso15118_3_public_sources.md      -- curated engineering rulebook

No network access is required and no copy of the paid standard is consumed.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_KEYS = (
    "tt_evse_slac_init",
    "tt_evse_match_session",
    "tt_match_response",
    "c_ev_match_retry",
    "tt_match_sequence",
    "tt_evse_match_mnbc",
    "tt_ev_atten_results",
    "tt_matching_repetition",
    "tt_matching_rate",
    "tt_match_join",
    "c_ev_start_atten_char_indseverestc_ev_start_atten_char_inds",
    "c_ev_match_mnbc",
    "tp_ev_batch_msg_interval",
)


def md(value) -> str:
    """Make a compact value safe inside a Markdown table cell."""
    return " ".join(str(value or "").split()).replace("|", "\\|")


def source_link(item) -> str:
    url = item.get("url") or ""
    return f"[source]({url})" if url.startswith(("http://", "https://")) else "—"


def render_markdown(payload, digest: str) -> str:
    result = payload["result"]
    corroborated = result["corroborated"]
    pending = result["uncorroborated"]
    by_key = {item["key"]: item for item in corroborated}
    states = collections.Counter(
        item.get("state") for item in payload.get("workflowProgress", [])
        if item.get("type") == "workflow_agent"
    )

    lines = [
        "# ISO 15118-3 public-source SLAC rulebook",
        "",
        "> Evidence status: public secondary sources only. The paid ISO "
        "15118-3 text was not opened, copied, or quoted. Values are "
        "second-hand attributions to Annex A/Table A.1 and must be described "
        "that way in publications.",
        "",
        "## Research status",
        "",
        f"- {len(corroborated)} findings passed an independent corroboration "
        f"check; {len(pending)} remain single-source or otherwise unresolved.",
        f"- Workflow agents: {states.get('done', 0)} completed and "
        f"{states.get('error', 0)} verifier jobs stopped at the Claude weekly "
        "quota. A pending item is not a rejected item; it is excluded from "
        "normative rules until independently verified.",
        f"- Archived input SHA-256: `{digest}`.",
        "- The full evidence, disagreements, URLs, and verifier reasoning are "
        "in `results/iso15118_3_public_sources.json`.",
        "",
        "## Critical correction to the detector",
        "",
        "The earlier fleet rule waited 10 s after `CM_SLAC_MATCH.REQ` and "
        "described that value as ISO-backed. The measurement remains useful, "
        "but the attribution was wrong. Two different clocks were conflated:",
        "",
        "| Observable condition | Public-source ISO symbol | Budget | Use |",
        "|---|---|---:|---|",
        "| `CM_SLAC_MATCH.REQ` sent; no `.CNF` | `TT_match_response` plus "
        "`C_EV_match_retry` | 200 ms × (1 + 2) = **600 ms** | ISO-derived arm |",
        "| Attenuation completed; no `CM_VALIDATE.REQ` or "
        "`CM_SLAC_MATCH.REQ` | `TT_EVSE_match_session` | **10 s** | ISO-derived arm |",
        "| `CM_SLAC_MATCH.REQ` sent; no `.CNF` | Fleet operating policy | "
        "**10 s** | Published empirical arm, retained for reproducibility |",
        "",
        "The 600 ms value is a conservative passive-observer derivation: one "
        "200 ms response window plus two retries. The table transcription "
        "describes `C_EV_match_retry=2` as retries, while EVerest's current "
        "loop treats the same constant as two total attempts. The composed "
        "600 ms deadline is therefore neither a directly published constant "
        "nor a conformance claim; it is also not a tuned threshold. The 10 s "
        "match-session timer is anchored in code at "
        "`CM_ATTEN_CHAR.RSP`, a later and therefore more lenient observable "
        "point than expiration of the 600 ms sounding window stated by one "
        "independent Table A.1 transcription.",
        "The retry-count discrepancy is directly inspectable in the "
        "[Table-A.1 transcription](https://github.com/cepsdev/v2g-guru-slac/blob/main/model/timing.ceps#L59-L60) "
        "and the current [EVerest match-request loop](https://github.com/EVerest/everest-core/blob/main/lib/everest/slac/fsm/ev/src/states/others.cpp#L137-L157).",
        "",
        "## Corroborated detector constants",
        "",
        "| Symbol | Value | Confidence | Meaning | Evidence |",
        "|---|---:|---|---|---|",
    ]
    for key in CORE_KEYS:
        item = by_key.get(key)
        if not item:
            continue
        lines.append(
            f"| `{md(item['symbol'])}` | {md(item['value'])} | "
            f"{md(item['confidence'])} | {md(item['meaning'])} | "
            f"{source_link(item)} |"
        )

    lines += [
        "",
        "## Pcap-observable state machine",
        "",
        "| Step | Exchange | Guard/check |",
        "|---:|---|---|",
        "| 1 | EV → EVSE `CM_SLAC_PARM.REQ`; EVSE → EV `.CNF` | "
        "Response window 200 ms; retry policy applies |",
        "| 2 | EV sends 3 × `CM_START_ATTEN_CHAR.IND` | 20–50 ms batch spacing |",
        "| 3 | EV sends 10 × `CM_MNBC_SOUND.IND` | 600 ms EVSE sounding window |",
        "| 4 | EVSE sends `CM_ATTEN_CHAR.IND`; EV returns `.RSP` | "
        "Response window 200 ms; retry policy applies |",
        "| 5 | Optional `CM_VALIDATE.REQ/.CNF` | Satisfies the EVSE match-session wait |",
        "| 6 | EV sends `CM_SLAC_MATCH.REQ`; EVSE returns `.CNF` | "
        "Response window 200 ms; public retry-count readings differ (2 or 3 "
        "total attempts), so the detector conservatively budgets 3 |",
        "| 7 | EV applies key; modems join the AVLN | `TT_match_join` 12 s |",
        "| 8 | SDP, TCP/TLS, SupportedAppProtocol, SessionSetup | "
        "ISO 15118-2 begins only after SLAC link-up |",
        "",
        "## Rule-arm configuration",
        "",
        "- `EV_AI_SLAC_RULE_MODE=empirical` (default): reproduces the "
        "published 10 s fleet result.",
        "- `EV_AI_SLAC_RULE_MODE=normative`: profile name for the public-source "
        "derived 600 ms unanswered-request budget and the separate 10 s "
        "missing-request timer; it is not a certification claim.",
        "- `EV_AI_SLAC_RULE_MODE=both`: evaluates the union; the normative "
        "rule normally fires first.",
        "",
        "All hard signals remain gated by absence of this session's own V2G "
        "traffic because both connectors share the PLC medium and their SLAC "
        "frames can appear in the same capture.",
        "",
        "## Excluded from hard rules",
        "",
        "- The 45 pending findings are preserved in the JSON archive but do "
        "not set thresholds.",
        "- Implementation defaults from QCA, pyPLC, or vendor stacks are not "
        "called normative unless a separate source explicitly attributes "
        "the same symbol/value to ISO 15118-3.",
        "- `CM_SLAC_MATCH.CNF → first V2G` has no corroborated tight "
        "application deadline; do not invent one from fleet observations.",
        "- Missing SLAC frames alone are not a fault because ring-buffer "
        "captures frequently start after matching.",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path,
                    help="Claude workflow JSON output (wllgq33hg.output)")
    ap.add_argument("--json-out", type=Path,
                    default=ROOT / "results" /
                    "iso15118_3_public_sources.json")
    ap.add_argument("--md-out", type=Path,
                    default=ROOT / "docs" /
                    "iso15118_3_public_sources.md")
    args = ap.parse_args()

    raw = args.input.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    result = payload.get("result", {})
    if not isinstance(result.get("corroborated"), list) or not isinstance(
            result.get("uncorroborated"), list):
        raise ValueError("input is not the expected ISO 15118-3 workflow output")

    digest = hashlib.sha256(raw).hexdigest()
    states = collections.Counter(
        item.get("state") for item in payload.get("workflowProgress", [])
        if item.get("type") == "workflow_agent"
    )
    archive = {
        "schema_version": 1,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "input_name": args.input.name,
        "input_sha256": digest,
        "workflow_summary": payload.get("summary"),
        "workflow_agent_count": payload.get("agentCount"),
        "workflow_completion": dict(states),
        "research_integrity": {
            "standard_text_used": False,
            "evidence_scope": "legitimate public secondary sources",
            "publication_caveat": (
                "Values are second-hand attributions to ISO 15118-3; "
                "do not imply direct verification against the paid standard."
            ),
        },
        "counts": {
            "corroborated": len(result["corroborated"]),
            "pending": len(result["uncorroborated"]),
        },
        "corroborated": result["corroborated"],
        "pending": result["uncorroborated"],
        "research_notes": result.get("notes", []),
        "workflow_logs": payload.get("logs", []),
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(archive, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args.md_out.write_text(render_markdown(payload, digest), encoding="utf-8")
    print(f"wrote {args.json_out}")
    print(f"wrote {args.md_out}")
    print(f"corroborated={archive['counts']['corroborated']} "
          f"pending={archive['counts']['pending']} sha256={digest}")


if __name__ == "__main__":
    main()

"""Detection policies the portable sidecar can run, and how each one is applied.

A desktop edition ships one benchmark (data/summary.json) and the detector must
run under the same policy that benchmark was measured with, so the policy is
read from the summary's `detectionPolicy.id` rather than configured separately.
Only whitelisted policies exist; an unknown id makes the sidecar report itself
as not ready instead of guessing.

The research code reads its switches from environment variables at import time
(core/feature_tracker.py, core/slac_features.py), so the worker must call
`apply_env` before importing any detector module and `verify_loaded` right
after, which fails loudly if the imported modules are not in the requested
state (PyInstaller runs with optimize=1, so this uses exceptions, not asserts).
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_POLICY = "baseline"

POLICIES: dict[str, dict[str, Any]] = {
    "baseline": {
        "label": "Baseline (fleet-tuned rules, no standard rule layers)",
        "iso2Rules": False,
        "slacRuleMode": "off",
        "env": {"EV_AI_ISO": "0", "EV_AI_ISO_VEC": "0", "EV_AI_SLAC": "0"},
    },
    "iso15118-standard": {
        "label": "ISO 15118-2 rule layer + ISO 15118-3 SLAC timers (normative)",
        "iso2Rules": True,
        "slacRuleMode": "normative",
        # EV_AI_ISO_VEC stays 0: the rule layer sees the ISO state, the
        # 33-feature vector the v4 weights were trained on does not change.
        "env": {
            "EV_AI_ISO": "1",
            "EV_AI_ISO_VEC": "0",
            "EV_AI_SLAC": "1",
            "EV_AI_SLAC_RULE_MODE": "normative",
        },
    },
}

# switches that must never leak in from the parent environment
_CLEARED_ENV = (
    "EV_AI_ISO",
    "EV_AI_ISO_VEC",
    "EV_AI_SLAC",
    "EV_AI_SLAC_RULE_MODE",
    "EV_AI_SLAC_WAIT",
    "EV_AI_NPD_RULE",
    "EV_AI_INDEX",
    "EV_AI_CLEAN_SAMPLE",
)


class PolicyError(ValueError):
    pass


def policy_id_from_summary(summary: dict[str, Any]) -> str:
    """The summary's policy id; a summary without one was measured on the baseline."""
    block = summary.get("detectionPolicy")
    if block is None:
        return DEFAULT_POLICY
    if not isinstance(block, dict) or not isinstance(block.get("id"), str):
        raise PolicyError("detectionPolicy must be an object with a string id")
    policy_id = block["id"].strip()
    if policy_id not in POLICIES:
        raise PolicyError(f"unknown detection policy {policy_id!r}")
    return policy_id


def public(policy_id: str) -> dict[str, Any]:
    policy = POLICIES[policy_id]
    return {
        "id": policy_id,
        "label": policy["label"],
        "iso2Rules": policy["iso2Rules"],
        "slacRuleMode": policy["slacRuleMode"],
    }


def apply_env(policy_id: str, environ: dict[str, str] | None = None) -> None:
    if policy_id not in POLICIES:
        raise PolicyError(f"unknown detection policy {policy_id!r}")
    env = os.environ if environ is None else environ
    for name in _CLEARED_ENV:
        env.pop(name, None)
    env.update(POLICIES[policy_id]["env"])


def verify_loaded(policy_id: str) -> None:
    """Check the imported research modules are in the state the policy asks for."""
    from core import feature_tracker as ft

    policy = POLICIES[policy_id]
    want_slac = policy["slacRuleMode"] != "off"
    problems = []
    if ft.ISO_ENABLED is not policy["iso2Rules"]:
        problems.append(f"ISO_ENABLED={ft.ISO_ENABLED}")
    if ft.ISO_IN_VECTOR:
        problems.append("ISO_IN_VECTOR=True (the packaged weights are 33 features wide)")
    if ft.FeatureState.N_FEATURES != 33:
        problems.append(f"N_FEATURES={ft.FeatureState.N_FEATURES}")
    if ft.SLAC_ENABLED is not want_slac:
        problems.append(f"SLAC_ENABLED={ft.SLAC_ENABLED}")
    if want_slac:
        from core import slac_features

        if slac_features.RULE_MODE != policy["slacRuleMode"]:
            problems.append(f"SLAC RULE_MODE={slac_features.RULE_MODE}")
    if problems:
        raise RuntimeError(
            f"detector modules do not match detection policy {policy_id!r}: " + ", ".join(problems)
        )

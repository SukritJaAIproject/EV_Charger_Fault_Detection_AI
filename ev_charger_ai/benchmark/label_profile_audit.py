"""Measure the impact of an alternative ground-truth profile.

This always compares the immutable published ``index.json`` with both outputs
from ``pipeline/relabel.py``. If a recomputed pre-review strict index is
available, it also separates changes that pre-date this ISO review from the
changes introduced by ``iso_reviewed``. It reports only sessions whose CSVs
were actually available during relabelling, so a fleet-wide metadata index
next to a held-out-only CSV mirror cannot create a misleading 40k-vs-8k
comparison.

    python benchmark/label_profile_audit.py \
      [sessions_dir] [output_json] [strict_index_name] [before_index_name]
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def family(meta):
    faults = meta.get("faults") or []
    return min(faults, key=lambda f: f[0])[1] if faults else "clean"


def counts(rows, censored_label=False):
    return collections.Counter(
        "censored" if censored_label and m.get("censored") else family(m)
        for m in rows
    )


def transition_summary(before, after_rows, censored=False):
    transitions = collections.Counter()
    anchor_delta = []
    for new in after_rows:
        old = before[new["session_key"]]
        old_family = family(old)
        new_family = ("censored" if censored and new.get("censored")
                      else family(new))
        transitions[(old_family, new_family)] += 1
        if old_family == new_family and old_family not in ("clean", "censored"):
            old_t = min(f[0] for f in old["faults"])
            new_t = min(f[0] for f in new["faults"])
            if abs(new_t - old_t) > 0.5:
                anchor_delta.append(new_t - old_t)
    anchor_delta.sort()
    return ([{"from": a, "to": b, "sessions": n}
             for (a, b), n in transitions.most_common()], {
        "sessions": len(anchor_delta),
        "median": (anchor_delta[len(anchor_delta) // 2]
                   if anchor_delta else None),
        "min": min(anchor_delta) if anchor_delta else None,
        "max": max(anchor_delta) if anchor_delta else None,
    })


def main(sess=r"C:\ev_fleet\sessions", output_json=None,
         strict_index_name="index_strict_pre_review.json",
         before_index_name="index_strict_pre_continuation.json"):
    paths = {
        "published": os.path.join(sess, "index.json"),
        "reviewed_all": os.path.join(sess, "index_iso_reviewed_all.json"),
        "reviewed_scoring": os.path.join(sess, "index_iso_reviewed.json"),
    }
    for name, path in paths.items():
        if not os.path.exists(path):
            raise SystemExit(f"missing {name}: {path}")
    strict_path = (os.path.join(sess, strict_index_name)
                   if strict_index_name else "")
    if strict_path and os.path.exists(strict_path):
        paths["pre_review_strict"] = strict_path
    before_path = (os.path.join(sess, before_index_name)
                   if before_index_name else "")
    if before_path and os.path.exists(before_path):
        paths["pre_continuation_strict"] = before_path

    published_list = load(paths["published"])
    reviewed_all = load(paths["reviewed_all"])
    reviewed_scoring = load(paths["reviewed_scoring"])
    published = {m["session_key"]: m for m in published_list}

    unavailable = [m["session_key"] for m in reviewed_all
                   if m["session_key"] not in published]
    if unavailable:
        raise SystemExit(f"{len(unavailable)} reviewed keys absent from index.json")

    transitions, anchor_delta = transition_summary(
        published, reviewed_all, censored=True
    )

    censor_reasons = collections.Counter(
        m.get("censor_reason") or "unspecified"
        for m in reviewed_all if m.get("censored")
    )
    quality = collections.Counter(
        str(q).split(":", 1)[0]
        for m in reviewed_all for q in m.get("quality_flags", [])
    )
    scoring_keys = {m["session_key"] for m in reviewed_scoring}
    old_scoring = [published[k] for k in scoring_keys]

    output = {
        "schema_version": 2,
        "sessions_dir": os.path.abspath(sess),
        "source_hashes": {name: digest(path) for name, path in paths.items()},
        "published_index_entries": len(published_list),
        "evaluated_sessions": len(reviewed_all),
        "scoring_sessions": len(reviewed_scoring),
        "censored_sessions": sum(bool(m.get("censored"))
                                 for m in reviewed_all),
        "distribution": {
            "published_on_evaluated": dict(counts(
                [published[m["session_key"]] for m in reviewed_all])),
            "reviewed_all": dict(counts(reviewed_all, censored_label=True)),
            "published_on_scoring_cohort": dict(counts(old_scoring)),
            "reviewed_scoring": dict(counts(reviewed_scoring)),
        },
        # Backward-compatible field: this is published -> reviewed. The
        # optional pre_review_strict block below isolates this review's delta.
        "transitions": transitions,
        "transition_basis": "published_to_reviewed",
        "censor_reasons": dict(censor_reasons),
        "quality_flags": dict(quality),
        "new_faults_on_published_clean": sum(
            family(published[m["session_key"]]) == "clean"
            and not m.get("censored") and family(m) != "clean"
            for m in reviewed_all
        ),
        "published_faults_now_clean": sum(
            family(published[m["session_key"]]) != "clean"
            and not m.get("censored") and family(m) == "clean"
            for m in reviewed_all
        ),
        "fault_anchor_delta_s": anchor_delta,
    }

    if "pre_review_strict" in paths:
        strict_list = load(paths["pre_review_strict"])
        strict = {m["session_key"]: m for m in strict_list}
        reviewed_keys = {m["session_key"] for m in reviewed_all}
        if set(strict) != reviewed_keys:
            raise SystemExit(
                "pre-review strict and reviewed-all indexes must cover the "
                f"same sessions (strict={len(strict)}, reviewed="
                f"{len(reviewed_keys)})"
            )
        published_to_strict, published_strict_anchor = transition_summary(
            published, strict_list
        )
        strict_to_reviewed, strict_reviewed_anchor = transition_summary(
            strict, reviewed_all, censored=True
        )
        strict_scoring = [strict[k] for k in scoring_keys]
        output["distribution"]["pre_review_strict_all"] = dict(
            counts(strict_list)
        )
        output["distribution"]["pre_review_strict_on_scoring_cohort"] = dict(
            counts(strict_scoring)
        )
        output["pre_review_strict"] = {
            "index": strict_index_name,
            "sessions": len(strict_list),
            "published_to_strict_transitions": published_to_strict,
            "strict_to_reviewed_transitions": strict_to_reviewed,
            "new_faults_on_strict_clean": sum(
                family(strict[m["session_key"]]) == "clean"
                and not m.get("censored") and family(m) != "clean"
                for m in reviewed_all
            ),
            "strict_faults_now_reviewed_clean": sum(
                family(strict[m["session_key"]]) != "clean"
                and not m.get("censored") and family(m) == "clean"
                for m in reviewed_all
            ),
            "fault_anchor_delta_s": {
                "published_to_strict": published_strict_anchor,
                "strict_to_reviewed": strict_reviewed_anchor,
            },
        }
        if "pre_continuation_strict" in paths:
            before_list = load(paths["pre_continuation_strict"])
            before = {m["session_key"]: m for m in before_list}
            core_fields = ("faults", "graceful_close",
                           "reached_current_demand")
            key_delta = set(before) ^ set(strict)
            field_delta = [
                key for key in set(before) & set(strict)
                if any(before[key].get(field) != strict[key].get(field)
                       for field in core_fields)
            ]
            output["pre_review_strict"][
                "pre_continuation_compatibility"
            ] = {
                "index": before_index_name,
                "compared_sessions": len(set(before) & set(strict)),
                "core_fields": list(core_fields),
                "key_differences": len(key_delta),
                "core_field_differences": len(field_delta),
            }

    out = output_json or os.path.join(
        ROOT, "results", "iso15118_label_profile_impact.json"
    )
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"evaluated={output['evaluated_sessions']} "
          f"scoring={output['scoring_sessions']} "
          f"censored={output['censored_sessions']}")
    print("published/evaluated:", output["distribution"]["published_on_evaluated"])
    if "pre_review_strict" in output:
        print("strict/evaluated:   ",
              output["distribution"]["pre_review_strict_all"])
    print("reviewed/all:       ", output["distribution"]["reviewed_all"])
    print("reviewed/scoring:   ", output["distribution"]["reviewed_scoring"])
    print("published -> reviewed changed transitions:")
    for item in output["transitions"]:
        if item["from"] != item["to"]:
            print(f"  {item['from']:<22} -> {item['to']:<22} "
                  f"{item['sessions']:>5}")
    if "pre_review_strict" in output:
        print("strict -> reviewed changed transitions:")
        for item in output["pre_review_strict"]["strict_to_reviewed_transitions"]:
            if item["from"] != item["to"]:
                print(f"  {item['from']:<22} -> {item['to']:<22} "
                      f"{item['sessions']:>5}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main(
        sys.argv[1] if len(sys.argv) > 1 else r"C:\ev_fleet\sessions",
        sys.argv[2] if len(sys.argv) > 2 else None,
        sys.argv[3] if len(sys.argv) > 3 else "index_strict_pre_review.json",
        (sys.argv[4] if len(sys.argv) > 4
         else "index_strict_pre_continuation.json"),
    )

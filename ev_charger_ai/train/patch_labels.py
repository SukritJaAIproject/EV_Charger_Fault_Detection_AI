"""Apply a corrected ground truth to existing step-matrix metadata.

Features never depend on labels, so a relabelling does not invalidate the
<split>_X.npy matrices — only the `faulty` / `t_fault` fields of
<split>_sessions.json, which is what the trainers read. Patching those in place
(keeping every sid exactly where it was) makes a retrain a training-only cost
instead of a rebuild.

    python train/patch_labels.py [index_strict.json]

Backs the originals up to <split>_sessions.legacy.json on first run, so the
weights behind the published leaderboards stay reproducible.
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.paths import DATA_ROOT as DATA, SESSIONS   # noqa: E402


def main(index_name="index_strict.json"):
    p = os.path.join(SESSIONS, index_name)
    if not os.path.exists(p):
        raise SystemExit(f"{p} not found — run pipeline/relabel.py first")
    with open(p, encoding="utf-8") as fh:
        new = {m["session_key"]: m for m in json.load(fh)}
    print(f"patching {DATA} from {index_name}")

    for split in ("train", "test"):
        q = os.path.join(DATA, f"{split}_sessions.json")
        if not os.path.exists(q):
            print(f"  {split}: absent, skipped")
            continue
        legacy = os.path.join(DATA, f"{split}_sessions.legacy.json")
        if not os.path.exists(legacy):
            shutil.copyfile(q, legacy)
        with open(q, encoding="utf-8") as fh:
            metas = json.load(fh)

        flipped = reanchored = missing = 0
        for m in metas:
            src = new.get(m["session_key"])
            if src is None:
                missing += 1
                continue
            faulty = bool(src["faults"])
            t_fault = (min(f[0] for f in src["faults"]) if faulty else None)
            if faulty != m["faulty"]:
                flipped += 1
            elif (faulty and m["t_fault"] is not None
                  and abs(t_fault - m["t_fault"]) > 0.5):
                reanchored += 1
            m["faulty"] = faulty
            m["t_fault"] = t_fault
        with open(q, "w", encoding="utf-8") as fh:
            json.dump(metas, fh, ensure_ascii=False)
        n_f = sum(1 for m in metas if m["faulty"])
        print(f"  {split}: {len(metas)} sessions, faulty now {n_f}; "
              f"{flipped} flipped, {reanchored} re-anchored, {missing} missing")
    print("originals kept as <split>_sessions.legacy.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "index_strict.json")

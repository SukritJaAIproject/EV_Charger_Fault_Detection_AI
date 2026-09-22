"""Dress rehearsal: run the ENTIRE pipeline on the draft telemetry copy.

Validates every stage (manifest -> sessionize -> dataset -> GPU training ->
competition) against real data while the corrected re-extraction runs.
All outputs land in data/draft_* and artifacts_draft/ — production paths
stay untouched.
"""
import csv
import json
import os
import sys

ROOT = r"F:\pcap_downloads\ev_charger_ai"
sys.path.insert(0, ROOT)

DRAFT_TEL = os.path.join(ROOT, "data", "telemetry_draft")
DRAFT_SESS = os.path.join(ROOT, "data", "sessions_draft")
DRAFT_ART = os.path.join(ROOT, "artifacts_draft")
DRAFT_RESULTS = os.path.join(ROOT, "results_draft")


def build_manifest():
    manifest = {}
    for station in sorted(os.listdir(DRAFT_TEL)):
        sdir = os.path.join(DRAFT_TEL, station)
        if not os.path.isdir(sdir):
            continue
        for conn in sorted(os.listdir(sdir)):
            cdir = os.path.join(sdir, conn)
            if not os.path.isdir(cdir):
                continue
            entries = []
            for f in os.listdir(cdir):
                if not f.endswith(".csv"):
                    continue
                path = os.path.join(cdir, f)
                first = last = None
                nrows = 0
                try:
                    with open(path, encoding="utf-8") as fh:
                        rd = csv.reader(fh)
                        next(rd, None)
                        for row in rd:
                            if not row or not row[0]:
                                continue
                            ts = float(row[0])
                            if first is None:
                                first = ts
                            last = ts
                            nrows += 1
                except Exception:  # noqa: BLE001
                    continue
                if first is not None:
                    entries.append({"file": f, "first": first, "last": last,
                                    "rows": nrows})
            entries.sort(key=lambda e: e["first"])
            manifest[f"{station}/{conn}"] = entries
    with open(os.path.join(DRAFT_TEL, "manifest.json"), "w") as fh:
        json.dump(manifest, fh)
    print(f"manifest: {len(manifest)} connectors", flush=True)


def patch_and_run():
    import pipeline.sessionize as sz
    sz.TELEMETRY = DRAFT_TEL
    sz.OUT = DRAFT_SESS
    sz.main()

    import core.stream as stream
    stream.SESS_DIR = DRAFT_SESS

    import train.build_dataset as bd
    draft_data = os.path.join(ROOT, "data", "draft")
    os.makedirs(draft_data, exist_ok=True)
    bd.DATA = draft_data
    for split in ("train", "test"):
        bd.build(split)

    import train.train_traditional as tt
    tt.DATA = draft_data
    tt.ART = DRAFT_ART
    tt.main()

    import train.train_nn_tools as tn
    tn.DATA = draft_data
    tn.ART = DRAFT_ART
    import models.nn_tools as nnt
    nnt.ART = DRAFT_ART
    seqs = tn.load_clean_v2g_sequences()
    print(f"clean sequences: {len(seqs)}", flush=True)
    tn.train_ae(seqs)
    tn.train_forecaster(seqs)

    import train.train_rl as tr
    tr.DATA = draft_data
    tr.ART = DRAFT_ART
    tr.main()

    import models.traditional as mt
    mt.ART = DRAFT_ART
    import models.rl_detector as mr
    mr.ART = DRAFT_ART

    import benchmark.run_competition as rc
    rc.RESULTS = DRAFT_RESULTS
    rc.main("test")


if __name__ == "__main__":
    os.makedirs(DRAFT_ART, exist_ok=True)
    os.makedirs(DRAFT_RESULTS, exist_ok=True)
    build_manifest()
    patch_and_run()
    print("REHEARSAL COMPLETE", flush=True)

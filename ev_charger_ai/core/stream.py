"""Session loading and streaming replay."""
import csv
import json
import os

from core.schema import Event

from core.paths import SESSIONS as SESS_DIR  # noqa: E402

_FLOATS = ("soc", "evse_v", "evse_i", "ev_target_v", "ev_target_i", "ev_max_v",
           "ev_max_i", "evse_max_v", "evse_max_i", "remaining_full_min",
           "remaining_bulk_min")


def load_index(path=None):
    """Session index with ground-truth labels.

    EV_AI_INDEX names an alternative index file inside the sessions dir (e.g.
    "index_strict.json" from pipeline/relabel.py). The benchmark scores
    against whatever index it loads here, so a relabelled ground truth has to
    be selected explicitly — a replay that silently picks up index.json will
    score new weights against old labels, which is exactly what happened to
    the first v2 run.
    """
    name = os.environ.get("EV_AI_INDEX", "index.json")
    with open(path or os.path.join(SESS_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def load_session_events(session_key, sess_dir=None):
    path = os.path.join(sess_dir or SESS_DIR, session_key + ".csv")
    events = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row.get("t"):
                continue
            kw = {"t": float(row["t"]), "kind": row["kind"], "msg": row["msg"]}
            for k in ("session", "resp_code", "evse_status", "isolation",
                      "notification", "ev_err", "ev_ready", "charge_complete",
                      "bulk_complete", "evse_processing", "limit_achieved",
                      "validation"):
                kw[k] = row.get(k) or ""
            for k in _FLOATS:
                v = row.get(k)
                kw[k] = float(v) if v else None
            ex = row.get("extra")
            if ex:
                try:
                    kw["extra"] = json.loads(ex)
                except json.JSONDecodeError:
                    pass
            events.append(Event(**kw))
    return events


def train_test_split_stations(index, test_stations):
    train, test = [], []
    for meta in index:
        (test if meta["station"] in test_stations else train).append(meta)
    return train, test

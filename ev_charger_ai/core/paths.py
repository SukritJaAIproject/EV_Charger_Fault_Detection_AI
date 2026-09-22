"""Single source of truth for where data lives.

The full fleet (~47k pcaps) produces ~250 GB of telemetry, sessions and
feature matrices — far beyond the 30 GB left on F:, so everything derived
lives on the 1 TB E: volume next to the pcaps. Override with env vars to point
at another tree (e.g. the old 37-station F: layout):

    EV_AI_PCAPS  root holding the pcap station folders
    EV_AI_DATA   root for telemetry/, sessions/, artifacts/, results/

Station keys
------------
The pcap root holds three groups that must stay distinguishable:

    <root>\\NNN_Name\\connectorK          main fleet download   -> key "NNN_Name"
    <root>\\2024\\Name\\connectorK        V2G_logs 2024 round   -> key "2024__Name"
    <root>\\2025\\Name\\connectorK        V2G_logs 2025 round   -> key "2025__Name"

A key is used verbatim as a directory name under telemetry/ and as the prefix
of session files, so it must not contain path separators (station names never
do). The double underscore is reserved for these synthetic prefixes.
"""
import hashlib
import json
import os

from core.findroot import resolve, station_count

# Drive letters move when a USB volume re-enumerates, so the default is found
# by folder name and contents rather than by letter. See core/findroot.py.
PCAP_ROOT = resolve("EV_AI_PCAPS", "pcap_downloads", score=station_count)
DATA_ROOT = resolve("EV_AI_DATA", "ev_charger_ai_data", "sessions\index.json")

# Each derived tree can be redirected on its own. Running two model variants
# (e.g. baseline features vs ISO 15118-2 conformance features) over the SAME
# sessions and the SAME split means sharing sessions/ and split.json while
# keeping the step matrices, weights and leaderboards apart:
#
#     EV_AI_SESSIONS   sessions/ + index.json   (shared between variants)
#     EV_AI_SPLIT      split.json               (shared — identical holdout)
#     EV_AI_DATA       <split>_{X,t,v2g,sid}.npy + <split>_sessions.json
#     EV_AI_ARTIFACTS  trained weights
#     EV_AI_RESULTS    leaderboards / records
TELEMETRY = os.environ.get("EV_AI_TELEMETRY", os.path.join(DATA_ROOT, "telemetry"))
SESSIONS = os.environ.get("EV_AI_SESSIONS", os.path.join(DATA_ROOT, "sessions"))
ARTIFACTS = os.environ.get("EV_AI_ARTIFACTS", os.path.join(DATA_ROOT, "artifacts"))
RESULTS = os.environ.get("EV_AI_RESULTS", os.path.join(DATA_ROOT, "results"))
LOGS = os.environ.get("EV_AI_LOGS", os.path.join(DATA_ROOT, "logs"))
SPLIT_FILE = os.environ.get("EV_AI_SPLIT", os.path.join(DATA_ROOT, "split.json"))

YEAR_GROUPS = ("2024", "2025")
GROUP_MAIN = "main"
SIG_CACHE = os.path.join(DATA_ROOT, "station_sigs.json")
CLONES_FILE = os.path.join(DATA_ROOT, "station_clones.json")


def site_of(key):
    """Station key -> physical site id, ignoring the capture round.

    "2024__29_EGCO Tower Station" and "2025__29_EGCO Tower Station" are the
    same charger captured in two rounds. They must not straddle the
    train/test split, so the holdout is drawn over sites, not station keys.
    """
    for y in YEAR_GROUPS:
        if key.startswith(y + "__"):
            return key[len(y) + 2:]
    return key


def station_signature(sdir):
    """Cheap content fingerprint of a station folder.

    Every pcap's connector, name and exact size, plus the first 64 KB of the
    first and last pcap. Two folders sharing this are the same capture: file
    sizes are byte-exact and a ring holds ~100 files, so a collision between
    genuinely different captures is not credible. Costs two reads per
    station rather than per file.
    """
    m = hashlib.sha1()
    first = last = None
    for c in ("connector1", "connector2"):
        d = os.path.join(sdir, c)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith(".pcap"):
                continue
            p = os.path.join(d, f)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            m.update(c.encode())
            m.update(f.encode("utf-8"))
            m.update(str(size).encode())
            if first is None:
                first = p
            last = p
    for p in (first, last):
        if p:
            try:
                with open(p, "rb") as fh:
                    m.update(fh.read(65536))
            except OSError:
                pass
    return m.hexdigest()


def _raw_stations(root):
    """Every station folder on disk, before de-duplication."""
    if not os.path.isdir(root):
        return
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        if name in YEAR_GROUPS:
            for sub in sorted(os.listdir(p)):
                sp = os.path.join(p, sub)
                if os.path.isdir(sp):
                    yield f"{name}__{sub}", sp, "v2g" + name
        elif name[:3].isdigit() and name[3:4] == "_":
            yield name, p, GROUP_MAIN


def clone_map(root=None, record=True):
    """-> {station_key: canonical_key}.

    The historical V2G_logs archive contains whole clusters of station
    folders that are byte-identical copies of one capture filed under
    different site names (measured: 65 "2024" folders hold 8 distinct
    captures). Processing them all would multiply the same sessions across
    the fleet and, worse, put identical sessions on both sides of the
    train/test split. The alphabetically first key of each cluster wins.

    Signatures are always recomputed (~20 s for 257 stations) rather than
    cached: the downloader keeps adding files, and a stale signature could
    silently mislabel a station as a clone.
    """
    root = root or PCAP_ROOT
    sigs = {key: station_signature(sdir)
            for key, sdir, _g in _raw_stations(root)}
    by_sig = {}
    for key in sorted(sigs):
        by_sig.setdefault(sigs[key], []).append(key)
    canon = {k: members[0] for members in by_sig.values() for k in members}
    if record:
        try:
            os.makedirs(DATA_ROOT, exist_ok=True)
            clusters = {m[0]: m for m in by_sig.values() if len(m) > 1}
            with open(CLONES_FILE, "w", encoding="utf-8") as fh:
                json.dump({"stations": len(sigs),
                           "distinct": len(by_sig),
                           "clone_folders": len(sigs) - len(by_sig),
                           "clusters": clusters}, fh,
                          ensure_ascii=False, indent=1)
        except OSError:
            pass
    return canon


def station_group(key):
    """'main' | 'v2g2024' | 'v2g2025' for a station key."""
    for y in YEAR_GROUPS:
        if key.startswith(y + "__"):
            return "v2g" + y
    return GROUP_MAIN


def station_src_dir(key):
    """Station key -> its pcap directory under PCAP_ROOT."""
    for y in YEAR_GROUPS:
        if key.startswith(y + "__"):
            return os.path.join(PCAP_ROOT, y, key[len(y) + 2:])
    return os.path.join(PCAP_ROOT, key)


def iter_stations(root=None, dedup=True):
    """Yield (station_key, station_dir, group) per distinct capture.

    With dedup=True (the default) byte-identical clone folders are collapsed
    to one canonical key — see clone_map().
    """
    root = root or PCAP_ROOT
    canon = clone_map(root) if dedup else None
    for key, sdir, group in _raw_stations(root):
        if canon is not None and canon.get(key, key) != key:
            continue
        yield key, sdir, group


def iter_connectors(station_dir):
    """Yield (connector_name, connector_dir) — only the canonical two."""
    for c in ("connector1", "connector2"):
        d = os.path.join(station_dir, c)
        if os.path.isdir(d):
            yield c, d


def ensure_dirs():
    for d in (TELEMETRY, SESSIONS, ARTIFACTS, RESULTS, LOGS):
        os.makedirs(d, exist_ok=True)

"""Deterministic station-level train/test split for the full fleet.

No session from a test station is ever trained on. The split is stratified
over the three data sources so every source is represented in the held-out
set, and the ten stations held out in the earlier 37-station runs stay held
out so those numbers remain comparable:

    legacy   the original 10 test stations (5 from the first 16, 5 from the
             second download)
    main     the rest of the main fleet download   -> ~20 % held out
    v2g2024  V2G_logs 2024 round (PT stations)     -> ~20 % held out
    v2g2025  V2G_logs 2025 round                   -> ~20 % held out

Selection is a seeded shuffle of station keys, so re-running on a bigger
fleet keeps earlier picks stable as long as the seed is unchanged.
Writes DATA_ROOT/split.json: {"test": [...], "train": [...], "group": {...}}.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.paths import SPLIT_FILE, station_group, site_of  # noqa: E402
from core.stream import load_index  # noqa: E402

LEGACY_TEST = {
    "003_7Eleven_Latphrao126", "007_Banbueng1", "010_BangBuaThong4",
    "013_BangKhla4", "016_BangnaTrad1",
    "019_BangPahan4", "023_Bangphra2_bangpha", "028_BanNaDoem",
    "031_BanTai", "037_Chachoengsao10",
}
# A previous run's split.json to inherit the held-out set from. Every station
# it held out stays held out, so a retrain on a bigger fleet is scored on the
# SAME test stations and the two leaderboards are directly comparable; only
# stations new to the fleet are drawn into the holdout on top of that.
PREV_SPLIT = os.environ.get("EV_AI_PREV_SPLIT",
                            r"E:\ev_charger_ai_data\split.json")
HOLDOUT_FRAC = 0.20
SEED = 20260908


def inherited_split():
    """(test, train) station sets of the previous run, or (set(), set()).

    Unreadable file -> no inheritance (first run ever). Same file as the one
    we are about to write -> no inheritance (a plain re-run of one root).
    """
    same = (os.path.normcase(os.path.abspath(PREV_SPLIT))
            == os.path.normcase(os.path.abspath(SPLIT_FILE)))
    if same:
        return set(), set()
    try:
        with open(PREV_SPLIT, encoding="utf-8") as fh:
            prev = json.load(fh)
    except OSError:
        return set(), set()
    return set(prev.get("test", [])), set(prev.get("train", []))


def main():
    index = load_index()
    stations = sorted({m["station"] for m in index})
    n_sessions = {}
    for m in index:
        n_sessions[m["station"]] = n_sessions.get(m["station"], 0) + 1

    groups = {s: station_group(s) for s in stations}
    # Hold out whole SITES: the same charger appears as both "2024__<name>"
    # and "2025__<name>", and putting one round in train and the other in
    # test would leak the site across the split.
    sites = {s: site_of(s) for s in stations}
    by_site = {}
    for s in stations:
        by_site.setdefault(sites[s], []).append(s)

    prev, prev_train = inherited_split()
    if prev:
        gone = sorted(prev - set(stations))
        if gone:
            # Comparability is the whole point of inheriting: refuse to
            # quietly score a different held-out set.
            raise SystemExit(
                f"{len(gone)} station(s) held out by {PREV_SPLIT} are missing "
                f"from the new session index (renamed? deduplicated as a "
                f"clone? no sessions?): {gone[:10]}")
    test = set(s for s in stations if s in LEGACY_TEST or s in prev)
    test |= {t for s in list(test) for t in by_site[sites[s]]}
    if prev:
        print(f"inherited {len(test)} held-out stations from {PREV_SPLIT}; "
              f"{len(set(stations) - prev - prev_train)} station(s) are new "
              f"to the fleet")
    rng = random.Random(SEED)
    for g in sorted(set(groups.values())):
        members = sorted(s for s in stations if groups[s] == g)
        want = max(1, round(HOLDOUT_FRAC * len(members)))
        have = sum(1 for s in members if s in test)
        # draw over sites, then take every station of the chosen site. When
        # inheriting, a station the previous run TRAINED on stays in train:
        # only stations new to the fleet may be drawn into the holdout, so the
        # new test set is the old one plus a share of the new stations.
        pool = sorted({sites[s] for s in members
                       if s not in test and s not in prev_train})
        rng.shuffle(pool)
        for site in pool:
            if have >= want:
                break
            add = [s for s in by_site[site] if s not in test]
            test.update(add)
            have += sum(1 for s in add if groups[s] == g)

    train = [s for s in stations if s not in test]
    leaked = sorted({sites[s] for s in train} & {sites[s] for s in test})
    if leaked:
        raise SystemExit(f"site leak across split: {leaked[:5]}")
    out = {
        "seed": SEED, "holdout_frac": HOLDOUT_FRAC,
        "legacy_test": sorted(LEGACY_TEST & set(stations)),
        "inherited_from": PREV_SPLIT if prev else None,
        "inherited_test": sorted(prev & set(stations)),
        "test": sorted(test), "train": train,
        "group": groups, "site": sites,
    }
    with open(SPLIT_FILE, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)

    print(f"stations: {len(stations)}  test: {len(test)}  train: {len(train)}")
    if prev:
        added = sorted(test - prev)
        print(f"  held out on top of the inherited {len(prev)}: "
              f"{len(added)} {added[:10]}")
    for g in sorted(set(groups.values())):
        members = [s for s in stations if groups[s] == g]
        t = [s for s in members if s in test]
        ns_t = sum(n_sessions[s] for s in t)
        ns_all = sum(n_sessions[s] for s in members)
        print(f"  {g:8s} stations {len(t):3d}/{len(members):3d} held out   "
              f"sessions {ns_t:5d}/{ns_all:5d} ({ns_t/max(ns_all,1)*100:.0f}%)")
    print(f"written: {SPLIT_FILE}")


if __name__ == "__main__":
    main()

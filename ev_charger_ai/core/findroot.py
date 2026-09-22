"""Find the data volume by what is on it, not by which letter Windows gave it.

The pcaps and every derived tree live on a USB drive. Windows hands USB volumes
whatever letter is free at plug-in time, and on this machine that has already
moved between E:, F: and G: - on 2026-09-16 the whole 250 GB tree "vanished"
purely because the Passport came back as G: while a different disk took E:.
Nothing was lost; every hardcoded path was simply pointing at the wrong volume.

So: name the folder, not the drive. `EV_AI_*` env vars still win, and a folder
next to this checkout still wins over a scan, but when neither is set the drive
letters are searched for a folder of that name carrying the expected marker.

    from core.findroot import find_dir
    root = find_dir("ev_charger_ai_data_v3", marker="sessions/index.json")
"""
import os
import string

__all__ = ["drive_letters", "find_dir", "resolve"]

_CACHE = {}


def drive_letters():
    """Existing drive roots, likeliest first: fixed data drives before C:."""
    out = [chr(c) + ":\\" for c in range(ord("D"), ord("Z") + 1)]
    out.append("C:\\")
    return [d for d in out if os.path.isdir(d)]


def _has_marker(path, marker):
    if not marker:
        return True
    return os.path.exists(os.path.join(path, *marker.replace("/", "\\").split("\\")))


def station_count(path):
    """How many station folders with a connector subfolder a pcap root holds.

    Used as a score rather than a yes/no: several drives carry a folder called
    `pcap_downloads` - an empty one left behind on the volume that took the old
    letter, an older 37-station copy beside the checkout, and the real fleet.
    First-match would pick whichever drive sorted first; most-stations picks
    the real one.
    """
    try:
        names = os.listdir(path)
    except OSError:
        return 0
    n = 0
    for nm in names:
        d = os.path.join(path, nm)
        if os.path.isdir(d) and (os.path.isdir(os.path.join(d, "connector1"))
                                 or os.path.isdir(os.path.join(d, "connector2"))):
            n += 1
    return n


def find_dir(name, marker=None, extra=(), score=None):
    """Locate <drive>\\<name>, else None.

    With `marker`, the first candidate carrying that relative path wins. With
    `score`, every candidate is measured and the highest non-zero wins. `extra`
    holds explicit candidates tried first. The answer is cached per process: a
    drive vanishing mid-run is a worse problem than a stale cache entry.
    """
    key = (name, marker, score is not None)
    if key in _CACHE and _CACHE[key] and os.path.isdir(_CACHE[key]):
        return _CACHE[key]
    cands = [c for c in (list(extra) +
                         [os.path.join(d, name) for d in drive_letters()])
             if c and os.path.isdir(c)]
    if score is not None:
        best, best_n = None, 0
        for c in cands:
            n = score(c)
            if n > best_n:
                best, best_n = c, n
        if best:
            _CACHE[key] = best
        return best
    for cand in cands:
        if _has_marker(cand, marker):
            _CACHE[key] = cand
            return cand
    return None


def resolve(env_var, name, marker=None, fallback=None, score=None):
    """Env var if set, else the scan, else `fallback` (which may not exist)."""
    env = os.environ.get(env_var)
    if env:
        return env
    found = find_dir(name, marker, score=score)
    return found or fallback or os.path.join("E:\\", name)


if __name__ == "__main__":
    print("drives:", " ".join(drive_letters()))
    print("  %-24s -> %s (by station count)"
          % ("pcap_downloads", find_dir("pcap_downloads", score=station_count)))
    for nm, mk in (("pcap_downloads", None),
                   ("ev_charger_ai_data", "sessions\\index.json"),
                   ("ev_charger_ai_data_v3", "sessions\\index.json"),
                   ("ev_charger_ai_data_v4", "sessions\\index.json")):
        print("  %-24s -> %s" % (nm, find_dir(nm, mk)))

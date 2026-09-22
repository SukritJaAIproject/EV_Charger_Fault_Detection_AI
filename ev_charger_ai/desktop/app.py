"""EGAT charger dashboard - local desktop app.

Double-click the Desktop shortcut (or run this file). It rebuilds the fleet
summary from the newest finished run, serves the dashboard on localhost, and
opens it in the default browser. Triage state is saved next to this file in
state\\triage.json, so marking a station "ส่งช่างแล้ว" survives a restart.

Standard library only - no pip install, no internet needed (web fonts fall
back to the system Thai UI face when offline).

    python app.py              open the dashboard
    python app.py --rebuild    force a data rebuild first
    python app.py --no-browser just serve
    python app.py --port 9000  pick the port
"""
import argparse
import http.server
import io
import json
import os
import shutil
import socket
import subprocess
import socketserver
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")
STATE = os.path.join(HERE, "state")
TMPL = os.path.join(HERE, "dashboard.tmpl.html")
FLEET = os.path.join(BUILD, "fleet.json")
PAGE = os.path.join(BUILD, "dashboard.html")
TRIAGE = os.path.join(STATE, "triage.json")
LOG = os.path.join(STATE, "app.log")
SIG = "egat-charger-dashboard"
DEFAULT_PORT = 8787

sys.path.insert(0, HERE)
import analyse  # noqa: E402
import build_data  # noqa: E402


# --------------------------------------------------------------------------
def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        os.makedirs(STATE, exist_ok=True)
        with io.open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def read_json(path, default):
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    """Write via a temp file so a crash mid-write cannot truncate the state."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
def source_index(root):
    return os.path.join(root, "sessions", "index.json")


def data_stale(root):
    """True when fleet.json is missing or older than the run it came from."""
    if not os.path.exists(FLEET):
        return True
    src = source_index(root)
    if not os.path.exists(src):
        return False
    return os.path.getmtime(src) > os.path.getmtime(FLEET)


def page_stale():
    """True when dashboard.html is missing or older than its inputs.

    The template is edited by hand far more often than the run changes, so it
    has to be part of this check - otherwise a template edit never reaches the
    browser and looks like the edit did nothing.
    """
    if not os.path.exists(PAGE):
        return True
    built = os.path.getmtime(PAGE)
    for src in (TMPL, FLEET):
        if os.path.exists(src) and os.path.getmtime(src) > built:
            return True
    return False


def render(status):
    """Write build/dashboard.html from the template + fleet.json."""
    tmpl = io.open(TMPL, encoding="utf-8").read()
    data = io.open(FLEET, encoding="utf-8").read().replace("<", "\\u003c")
    html = tmpl.replace("__FLEET_JSON__", data)
    os.makedirs(BUILD, exist_ok=True)
    io.open(PAGE, "w", encoding="utf-8").write(html)
    status["page_bytes"] = len(html.encode("utf-8"))


def prepare(status, force=False):
    """Refresh fleet.json + dashboard.html when the run has moved on."""
    root = build_data.find_root(os.environ.get("EV_AI_DATA"))
    status["root"] = root
    if root is None:
        status["error"] = ("ไม่พบผลการวิเคราะห์ - หา sessions\\index.json ไม่เจอใน "
                           + ", ".join(c for c in build_data.CANDIDATES if c))
        return os.path.exists(PAGE)
    if force or data_stale(root):
        log("rebuilding fleet summary from %s" % root)
        out = build_data.build(root, FLEET)
        log("rebuilt: %d stations, %d sessions"
            % (out["fleet"]["stations"], out["fleet"]["sessions"]))
    meta = read_json(FLEET, {})
    status["fleet"] = meta.get("fleet", {})
    status["generated"] = meta.get("generated", "")
    if force or page_stale():
        render(status)
        log("rendered dashboard.html (%d bytes)" % status.get("page_bytes", 0))
    status.pop("error", None)
    return True


# --------------------------------------------------------------------------
_STOP = []          # holds the shutdown callable; a plain function assigned to
                    # the Handler class would bind as a method and break

# ----------------------------- upload + analyse jobs ----------------------
JOBS = {}                       # id -> {state, step, result, error, files}
JOBS_LOCK = threading.Lock()
JOBS_DIR = os.path.join(STATE, "jobs")
KEEP_JOBS = 3
MAX_UPLOAD = 400 * 1024 * 1024


def _new_job():
    """Fresh job id, oldest job folders pruned so uploads cannot pile up."""
    with JOBS_LOCK:
        jid = "j%d" % int(time.time() * 1000)
        JOBS[jid] = {"state": "staging", "step": "", "files": [],
                     "result": None, "error": None, "started": time.time()}
        old = sorted(JOBS, key=lambda k: JOBS[k]["started"])[:-KEEP_JOBS]
        for k in old:
            if JOBS[k]["state"] in ("running", "staging"):
                continue
            JOBS.pop(k, None)
            shutil.rmtree(os.path.join(JOBS_DIR, k), ignore_errors=True)
    os.makedirs(os.path.join(JOBS_DIR, jid), exist_ok=True)
    return jid


def analysis_python():
    """Interpreter for the analysis subprocess.

    The five detectors import torch and xgboost, which live in the project's
    conda env, while this app deliberately runs on the stdlib-only system
    Python. So the analysis runs out-of-process on whichever interpreter has
    the models - which also keeps a tshark or model crash out of the server.
    Returns (python, has_models).
    """
    for cand in [os.environ.get("EV_AI_PYTHON"),
                 r"C:\Users\%s\anaconda3\envs\ev_ai\python.exe" % os.environ.get("USERNAME", ""),
                 r"C:\Users\user1\anaconda3\envs\ev_ai\python.exe"]:
        if cand and os.path.exists(cand):
            return cand, True
    return sys.executable, False


def _run_job(jid, models, root):
    job = JOBS[jid]

    def note(msg):
        job["step"] = msg
        log("analyse %s: %s" % (jid, msg))

    try:
        job["state"] = "running"
        py, full = analysis_python()
        if models and not full:
            note("no torch on this interpreter; only rule-based models can run")
        out_json = os.path.join(JOBS_DIR, jid, "result.json")
        cmd = [py, "-X", "utf8", os.path.join(HERE, "analyse.py"),
               "--json", out_json]
        if models:
            cmd += ["--models", ",".join(models)]
        else:
            cmd.append("--no-ai")
        if root:
            cmd += ["--data-root", root]
        cmd += [f["path"] for f in job["files"]]
        note("starting the decoder")
        proc = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        tail = []
        for line in proc.stdout:
            line = line.rstrip()
            if line.startswith("#"):
                note(line[1:])
            elif line:
                tail.append(line)
                del tail[:-25]
        rc = proc.wait()
        if rc != 0 or not os.path.exists(out_json):
            raise RuntimeError("analysis failed (rc=%s) %s"
                               % (rc, " | ".join(tail[-3:])))
        job["result"] = read_json(out_json, None)
        if job["result"] is None:
            raise RuntimeError("analysis produced no result")
        job["state"] = "done"
        job["step"] = ""
    except Exception as exc:                    # noqa: BLE001
        job["state"] = "error"
        job["error"] = str(exc) or exc.__class__.__name__
        log("analyse %s FAILED\n%s" % (jid, traceback.format_exc()))
    finally:
        # the decoded CSVs can be far larger than the pcaps; keep only the answer
        shutil.rmtree(os.path.join(JOBS_DIR, jid, "work"), ignore_errors=True)
        try:
            os.remove(os.path.join(JOBS_DIR, jid, "result.json"))
        except OSError:
            pass
        for f in job["files"]:
            try:
                os.remove(f["path"])
            except OSError:
                pass


def _job_view(jid):
    job = JOBS.get(jid)
    if not job:
        return None
    return {"job": jid, "state": job["state"], "step": job["step"],
            "error": job["error"],
            "files": [{"name": f["name"], "bytes": f["bytes"]}
                      for f in job["files"]],
            "result": job["result"]}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "EgatDash/1.0"
    status = {}

    def log_message(self, fmt, *args):       # quiet; we keep our own log
        pass

    # -- helpers ----------------------------------------------------------
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _query(self):
        """Query string as {key: [values]}, blanks kept.

        keep_blank_values matters: "models=" means "no model at all", which is
        a different instruction from omitting the parameter.
        """
        raw = self.path.split("?", 1)[1] if "?" in self.path else ""
        return urllib.parse.parse_qs(raw, keep_blank_values=True)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 1 << 20:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- routes -----------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/index.html"):
                # re-render when the template has been edited since the last
                # build, so a page change shows up on a plain browser refresh
                if page_stale():
                    try:
                        render(self.status)
                        log("re-rendered (template changed)")
                    except Exception:
                        log("re-render failed\n%s" % traceback.format_exc())
                if not os.path.exists(PAGE):
                    return self._send(503, self._error_page(), "text/html; charset=utf-8")
                with io.open(PAGE, "rb") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            if path == "/api/ping":
                return self._send(200, {"app": SIG, "root": self.status.get("root"),
                                        "generated": self.status.get("generated", ""),
                                        "fleet": self.status.get("fleet", {})})
            if path == "/api/triage":
                return self._send(200, read_json(TRIAGE, {}))
            if path == "/api/analyse":
                q = self._query()
                view = _job_view((q.get("job") or [""])[0])
                if view is None:
                    return self._send(404, {"error": "no such job"})
                return self._send(200, view)
            if path == "/favicon.ico":
                ico = os.path.join(HERE, "icon.ico")
                if os.path.exists(ico):
                    with io.open(ico, "rb") as fh:
                        return self._send(200, fh.read(), "image/x-icon")
                return self._send(404, b"", "text/plain")
            return self._send(404, {"error": "not found"})
        except Exception:
            log("GET %s failed\n%s" % (path, traceback.format_exc()))
            return self._send(500, {"error": "internal"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/triage":
                b = self._body()
                key = b.get("k")
                if not key:
                    return self._send(400, {"error": "missing k"})
                allt = read_json(TRIAGE, {})
                allt[key] = {"s": b.get("s", "open"), "n": b.get("n", "")[:200],
                             "at": b.get("at", time.strftime("%Y-%m-%d %H:%M"))}
                write_json(TRIAGE, allt)
                return self._send(200, {"ok": True, "n": len(allt)})
            if path == "/api/upload":
                q = self._query()
                jid = (q.get("job") or [""])[0] or _new_job()
                job = JOBS.get(jid)
                if not job or job["state"] != "staging":
                    return self._send(400, {"error": "job is not accepting files"})
                name = os.path.basename((q.get("name") or ["upload.pcap"])[0])
                if not name.lower().endswith((".pcap", ".pcapng", ".cap")):
                    return self._send(400, {"error": "only .pcap/.pcapng files"})
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0 or n > MAX_UPLOAD:
                    return self._send(400, {"error": "bad file size"})
                if len(job["files"]) >= analyse.MAX_FILES:
                    return self._send(400, {"error": "too many files"})
                dst = os.path.join(JOBS_DIR, jid, "%02d_%s" % (len(job["files"]), name))
                left = n
                with io.open(dst, "wb") as fh:
                    while left > 0:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            break
                        fh.write(chunk)
                        left -= len(chunk)
                job["files"].append({"name": name, "path": dst, "bytes": n})
                return self._send(200, {"job": jid, "files": len(job["files"])})
            if path == "/api/analyse":
                q = self._query()
                jid = (q.get("job") or [""])[0]
                job = JOBS.get(jid)
                if not job:
                    return self._send(404, {"error": "no such job"})
                if job["state"] != "staging":
                    return self._send(400, {"error": "already started"})
                if not job["files"]:
                    return self._send(400, {"error": "no files"})
                raw = (q.get("models") or [None])[0]
                if raw is None:
                    models = analyse.ALL_MODELS if (q.get("ai") or ["1"])[0] != "0" else []
                else:
                    models = [m for m in raw.split(",") if m in analyse.FACTORY]
                threading.Thread(target=_run_job, daemon=True,
                                 args=(jid, models, self.status.get("root"))).start()
                return self._send(200, {"job": jid, "state": "running"})
            if path == "/api/rebuild":
                ok = prepare(self.status, force=True)
                if not ok or self.status.get("error"):
                    return self._send(503, {"error": self.status.get("error", "rebuild failed")})
                return self._send(200, {"ok": True,
                                        "generated": self.status.get("generated", ""),
                                        "fleet": self.status.get("fleet", {})})
            if path == "/api/quit":
                self._send(200, {"ok": True})
                log("shutdown requested from the page")
                if _STOP:
                    threading.Thread(target=_STOP[0], daemon=True).start()
                return None
            return self._send(404, {"error": "not found"})
        except Exception:
            log("POST %s failed\n%s" % (path, traceback.format_exc()))
            return self._send(500, {"error": "internal"})

    def _error_page(self):
        msg = self.status.get("error", "ยังไม่มีข้อมูล")
        return ("<!doctype html><meta charset=utf-8>"
                "<title>EGAT dashboard</title>"
                "<body style='font-family:Segoe UI,Tahoma,sans-serif;margin:48px;"
                "background:#e9edef;color:#0e161b'>"
                "<h1 style='font-size:20px'>เปิดแผงควบคุมไม่ได้</h1>"
                "<p>%s</p><p style='color:#4a555d;font-size:14px'>"
                "ต่อไดรฟ์ E: แล้วกดรีเฟรชหน้านี้ หรือกำหนดตัวแปร EV_AI_DATA "
                "ให้ชี้ไปยังโฟลเดอร์ผลการวิเคราะห์</p></body>") % msg


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False      # so a busy port is detected, not stolen


# --------------------------------------------------------------------------
def already_running(port):
    """Return True when OUR app already owns this port."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port,
                                    timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == SIG
    except Exception:
        return False


def pick_port(preferred):
    for p in [preferred] + [preferred + i for i in range(1, 12)]:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    if already_running(a.port):
        log("already running on %d - opening the existing window" % a.port)
        if not a.no_browser:
            webbrowser.open("http://127.0.0.1:%d/" % a.port)
        return 0

    status = {}
    try:
        prepare(status, force=a.rebuild)
    except Exception:
        status["error"] = "สร้างข้อมูลไม่สำเร็จ - ดูรายละเอียดใน state\\app.log"
        log("prepare failed\n%s" % traceback.format_exc())

    port = pick_port(a.port)
    if not port:
        log("no free port near %d" % a.port)
        return 1

    Handler.status = status
    httpd = Server(("127.0.0.1", port), Handler)

    def stop():
        time.sleep(0.4)          # let the 200 reach the browser first
        httpd.shutdown()
    _STOP.append(stop)
    url = "http://127.0.0.1:%d/" % port
    log("serving %s  (root=%s)" % (url, status.get("root")))
    if status.get("error"):
        log("warning: " + status["error"])
    if not a.no_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())

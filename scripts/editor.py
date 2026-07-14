"""Local web editor for fine-tuning autoclip jobs (parts / subtitles / SFX).

Usage:
    uv run scripts/editor.py [--port 8765]

Serves http://localhost:8765 — pick a job, drag part boundaries on the
timeline, edit word timings and SFX, then save + re-render from the browser.
Stdlib only (no extra deps). Each job needs jobs/<name>/job.json:
    {"video": "C:/path/to/source.mp4", "vertical": true}
"""
import argparse
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS = os.path.join(ROOT, "jobs")
renders = {}  # job name -> Popen

CTYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
    ".mp4": "video/mp4", ".jpg": "image/jpeg", ".png": "image/png",
    ".otf": "font/otf", ".ttf": "font/ttf", ".json": "application/json; charset=utf-8",
}


_FONT_CACHE = None


def font_list():
    """Scan fonts/ and return [{file, family, style, full}] (full = ASS/libass name)."""
    global _FONT_CACHE
    if _FONT_CACHE is not None:
        return _FONT_CACHE
    out = []
    fdir = os.path.join(ROOT, "fonts")
    if os.path.isdir(fdir):
        try:
            from PIL import ImageFont
        except ImportError:
            return out
        for fn in sorted(os.listdir(fdir)):
            if fn.lower().endswith((".otf", ".ttf")):
                try:
                    fam, sty = ImageFont.truetype(os.path.join(fdir, fn), 12).getname()
                    full = fam if sty.lower() in ("regular", "") else f"{fam} {sty}"
                    out.append({"file": fn, "family": fam, "style": sty, "full": full})
                except OSError:
                    pass
    _FONT_CACHE = out
    return out


def safe_job(name):
    if not re.fullmatch(r"[\w.\-]+", name):
        raise ValueError("bad job name")
    return os.path.join(JOBS, name)


def read_json(path, default=None):
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ---- helpers -------------------------------------------------------
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        if not os.path.isfile(path):
            return self.send_json({"error": "not found: " + path}, 404)
        size = os.path.getsize(path)
        ctype = CTYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        start, end = 0, size - 1
        code = 200
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                else:  # suffix range: bytes=-N
                    start = max(0, size - int(m.group(2)))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 256, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    return
                remaining -= len(chunk)

    def read_body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else None

    def serve_static(self, rel):
        path = os.path.normpath(os.path.join(ROOT, rel.lstrip("/")))
        if not path.startswith(ROOT):
            return self.send_json({"error": "forbidden"}, 403)
        self.send_file(path)

    # ---- routes --------------------------------------------------------
    def do_GET(self):
        p = self.path.split("?")[0]
        try:
            if p == "/":
                return self.send_file(os.path.join(ROOT, "scripts", "editor.html"))
            if p == "/api/fonts":
                return self.send_json(font_list())
            if p == "/api/jobs":
                out = []
                if os.path.isdir(JOBS):
                    for name in sorted(os.listdir(JOBS)):
                        d = os.path.join(JOBS, name)
                        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "transcript.json")):
                            out.append(name)
                return self.send_json(out)
            m = re.match(r"^/api/job/([\w.\-]+)$", p)
            if m:
                d = safe_job(m.group(1))
                job = read_json(os.path.join(d, "job.json"), {})
                tr = read_json(os.path.join(d, "transcript_clean.json")) or \
                     read_json(os.path.join(d, "transcript.json"))
                clips = read_json(os.path.join(d, "clips.json"), [])
                return self.send_json({
                    "job": job, "transcript": tr, "clips": clips,
                    "outputs": self.list_outputs(m.group(1)),
                })
            m = re.match(r"^/video/([\w.\-]+)$", p)
            if m:
                job = read_json(os.path.join(safe_job(m.group(1)), "job.json"), {})
                v = job.get("video")
                if not v or not os.path.isfile(v):
                    return self.send_json({"error": "video path missing in job.json"}, 404)
                return self.send_file(v)
            m = re.match(r"^/api/render/([\w.\-]+)/status$", p)
            if m:
                name = m.group(1)
                proc = renders.get(name)
                log = ""
                logp = os.path.join(safe_job(name), "render.log")
                if os.path.isfile(logp):
                    with open(logp, encoding="utf-8", errors="replace") as f:
                        log = "".join(f.readlines()[-30:])
                return self.send_json({
                    "running": proc is not None and proc.poll() is None,
                    "code": None if proc is None else proc.poll(),
                    "log": log,
                    "outputs": self.list_outputs(name),
                })
            if p.startswith("/jobs/") or p.startswith("/fonts/"):
                return self.serve_static(p)
            self.send_json({"error": "not found"}, 404)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            try:
                self.send_json({"error": str(e)}, 500)
            except OSError:
                pass

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            m = re.match(r"^/api/job/([\w.\-]+)/clips$", p)
            if m:
                write_json(os.path.join(safe_job(m.group(1)), "clips.json"), self.read_body())
                return self.send_json({"ok": True})
            m = re.match(r"^/api/job/([\w.\-]+)/transcript$", p)
            if m:
                write_json(os.path.join(safe_job(m.group(1)), "transcript_clean.json"), self.read_body())
                return self.send_json({"ok": True})
            m = re.match(r"^/api/render/([\w.\-]+)$", p)
            if m:
                name = m.group(1)
                if name in renders and renders[name].poll() is None:
                    return self.send_json({"error": "already running"}, 409)
                d = safe_job(name)
                job = read_json(os.path.join(d, "job.json"), {})
                video = job.get("video")
                if not video or not os.path.isfile(video):
                    return self.send_json({"error": "video path missing in job.json"}, 400)
                tr = os.path.join(d, "transcript_clean.json")
                if not os.path.isfile(tr):
                    tr = os.path.join(d, "transcript.json")
                body = self.read_body() or {}
                vertical = body.get("vertical", job.get("vertical", True))
                cmd = ["uv", "run", "scripts/render.py", video, tr,
                       os.path.join(d, "clips.json"), os.path.join(d, "out")]
                if vertical:
                    cmd.append("--vertical")
                logf = open(os.path.join(d, "render.log"), "w", encoding="utf-8")
                renders[name] = subprocess.Popen(cmd, cwd=ROOT, stdout=logf,
                                                 stderr=subprocess.STDOUT)
                return self.send_json({"ok": True})
            self.send_json({"error": "not found"}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def list_outputs(self, name):
        outdir = os.path.join(safe_job(name), "out")
        out = []
        if os.path.isdir(outdir):
            for f in sorted(os.listdir(outdir)):
                if f.endswith(".mp4") and "_p" not in f:
                    st = os.stat(os.path.join(outdir, f))
                    out.append({"file": f, "mtime": int(st.st_mtime), "size": st.st_size})
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"autoclip editor: http://localhost:{args.port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()

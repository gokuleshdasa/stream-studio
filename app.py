"""
Stream Studio - download & clip media from any site (yt-dlp + ffmpeg).
Backend: Flask + yt-dlp + ffmpeg.
"""
import os
import re
import sys
import json
import time
import uuid
import shutil
import tempfile
import zipfile
import threading
import subprocess
import urllib.request
from pathlib import Path

# ---- yt-dlp self-update override --------------------------------------------
# A newer yt-dlp can be unpacked into this user-writable folder; if present it
# is loaded INSTEAD of the copy frozen inside the .exe, so the app keeps working
# when YouTube changes without us shipping a whole new build.
EXTENSION_VERSION = "1.1.0"  # version of the chrome-extension shipped with this app

def _override_dir():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Stream Studio" / "pkgs"
OVERRIDE_DIR = _override_dir()

import importlib.abc
import importlib.machinery


class _OverrideFinder(importlib.abc.MetaPathFinder):
    """Loads yt_dlp from OVERRIDE_DIR ahead of PyInstaller's frozen importer."""
    def __init__(self, path):
        self._path = [str(path)]

    def find_spec(self, name, target=None, *args, **kwargs):
        if name == "yt_dlp" or name.startswith("yt_dlp."):
            return importlib.machinery.PathFinder.find_spec(name, self._path)
        return None


_override_active = (OVERRIDE_DIR / "yt_dlp" / "__init__.py").exists()
if _override_active:
    sys.meta_path.insert(0, _OverrideFinder(OVERRIDE_DIR))

from flask import Flask, request, jsonify, send_file, render_template, abort, Response

# Self-healing: if an updated yt_dlp fails to import for any reason, discard the
# override and fall back to the copy frozen in the .exe so the app never crashes.
try:
    import yt_dlp
except Exception:
    if _override_active:
        sys.meta_path[:] = [m for m in sys.meta_path if not isinstance(m, _OverrideFinder)]
        for _m in [k for k in list(sys.modules) if k == "yt_dlp" or k.startswith("yt_dlp.")]:
            del sys.modules[_m]
        shutil.rmtree(OVERRIDE_DIR / "yt_dlp", ignore_errors=True)
        _override_active = False
        import yt_dlp
    else:
        raise

# ---- path resolution (works both as `python app.py` and as a frozen exe) ----
FROZEN = getattr(sys, "frozen", False)
# RES_DIR: where bundled read-only assets live (templates, static, ffmpeg.exe)
RES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
EXE_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).parent

# When installed (frozen) the .exe may live in Program Files (read-only), so
# finished files go to the user's Downloads and scratch goes to the temp dir.
if FROZEN:
    OUT = Path.home() / "Downloads" / "Stream Studio"
    WORK = Path(tempfile.gettempdir()) / "StreamStudio_work"
else:
    OUT = EXE_DIR / "downloads"
    WORK = EXE_DIR / "work"
WORK.mkdir(exist_ok=True, parents=True)
OUT.mkdir(exist_ok=True, parents=True)

# ffmpeg: prefer a bundled copy (in the bundle / next to the exe), else PATH
def _resolve_ffmpeg():
    for cand in (RES_DIR / "ffmpeg.exe", EXE_DIR / "ffmpeg.exe"):
        if cand.exists():
            return str(cand)
    return "ffmpeg"
FFMPEG = _resolve_ffmpeg()

# Deno JS runtime: newer yt-dlp uses it for some YouTube player checks. If a
# bundled (or system) deno is found, put its folder on PATH so yt-dlp finds it.
def _resolve_deno():
    for cand in (RES_DIR / "deno.exe", EXE_DIR / "deno.exe"):
        if cand.exists():
            return cand
    return None
DENO = _resolve_deno()
if DENO:
    os.environ["PATH"] = str(DENO.parent) + os.pathsep + os.environ.get("PATH", "")
# With a JS runtime available, let yt-dlp fetch its EJS challenge-solver script
# so all YouTube formats are reachable. (Fetched once from GitHub, then cached.)
EJS_OPTS = {"remote_components": ["ejs:github"]} if DENO else {}

# Prevent ffmpeg/child processes from flashing a console window when the app
# itself runs windowed (no console) as a background tray process.
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


# ---- yt-dlp update helpers --------------------------------------------------
def _ver_tuple(v):
    parts = re.split(r"[.\-]", str(v))
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def current_ytdlp():
    try:
        return yt_dlp.version.__version__
    except Exception:
        return "0"


def latest_ytdlp():
    """Return (version, wheel_url) of the newest yt-dlp on PyPI."""
    with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=15) as r:
        data = json.load(r)
    ver = data["info"]["version"]
    url = None
    for f in data["releases"].get(ver, []):
        if f["filename"].endswith(".whl"):
            url = f["url"]
            break
    return ver, url


def ytdlp_update_available():
    try:
        latest, _ = latest_ytdlp()
        return _ver_tuple(latest) > _ver_tuple(current_ytdlp()), latest
    except Exception:
        return False, None


def install_ytdlp(url):
    """Download the yt-dlp wheel and unpack its package into OVERRIDE_DIR."""
    OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "StreamStudio"})
    with urllib.request.urlopen(req, timeout=120) as r:
        blob = r.read()
    tmp = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(__import__("io").BytesIO(blob)) as z:
        z.extractall(tmp)
    src = tmp / "yt_dlp"
    if not src.exists():
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("downloaded wheel did not contain yt_dlp")
    target = OVERRIDE_DIR / "yt_dlp"
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.move(str(src), str(target))
    shutil.rmtree(tmp, ignore_errors=True)

app = Flask(__name__,
            template_folder=str(RES_DIR / "templates"),
            static_folder=str(RES_DIR / "static"))

# In-memory job registry. job_id -> dict(status, stage, progress, message, files, error)
JOBS = {}
JOBS_LOCK = threading.Lock()

# ---- audio / video format tables -------------------------------------------
AUDIO_CODECS = {
    "mp3":  ["-c:a", "libmp3lame"],
    "aac":  ["-c:a", "aac"],
    "m4a":  ["-c:a", "aac"],
    "wav":  ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "opus": ["-c:a", "libopus"],
    "ogg":  ["-c:a", "libvorbis"],
}
LOSSLESS_AUDIO = {"wav", "flac"}

VIDEO_CONTAINER = {
    "mp4":  {"v": "libx264", "a": "aac"},
    "mkv":  {"v": "libx264", "a": "aac"},
    "webm": {"v": "libvpx-vp9", "a": "libopus"},
}


def sanitize(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\n\r\t]+', "_", name or "")
    name = re.sub(r"\s+", " ", name).strip()
    return (name or "clip")[:80]


def hhmmss_ok(v):
    return isinstance(v, (int, float)) and v >= 0


def set_job(job_id, **kw):
    with JOBS_LOCK:
        JOBS.setdefault(job_id, {})
        JOBS[job_id].update(kw)


def get_job(job_id):
    with JOBS_LOCK:
        return dict(JOBS.get(job_id, {}))


# ---- in-browser preview proxy (works for any site, not just YouTube) --------
PREVIEWS = {}  # token -> direct media URL
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _is_direct(f):
    # A directly-playable stream (plain http/https), not HLS/DASH manifests.
    proto = (f.get("protocol") or "")
    return bool(f.get("url")) and proto in ("https", "http", "")


def _pick_preview(info):
    """Return (media_kind, direct_url) for a lightweight HTML5 preview.

    Codecs are often unreported (None) on progressive streams, so we key off
    protocol + height rather than codec names, and avoid HLS/DASH manifests.
    """
    fmts = info.get("formats") or []

    # progressive video (has a frame height) over plain http
    vids = [f for f in fmts if _is_direct(f)
            and (f.get("height") or 0) > 0 and f.get("vcodec") != "none"]
    if vids:
        vids.sort(key=lambda f: (f.get("height") or 9999))
        for f in vids:
            if (f.get("height") or 0) >= 240:   # small but watchable preview
                return "video", f["url"]
        return "video", vids[-1]["url"]

    # audio-only sources (SoundCloud, Bandcamp, podcasts…)
    auds = [f for f in fmts if _is_direct(f)
            and not (f.get("height") or 0) and f.get("acodec") != "none"]
    if auds:
        auds.sort(key=lambda f: (f.get("abr") or 0))
        return "audio", auds[len(auds) // 2]["url"]

    if info.get("url") and (info.get("protocol") or "") in ("https", "http", ""):
        kind = "video" if (info.get("height") or 0) else "audio"
        return kind, info["url"]

    has_video = any((f.get("height") or 0) for f in fmts)
    return ("video" if has_video else "audio"), None


def _register_preview(direct_url):
    if not direct_url:
        return None
    token = uuid.uuid4().hex[:16]
    PREVIEWS[token] = direct_url
    if len(PREVIEWS) > 60:                # cap memory
        for k in list(PREVIEWS)[:-60]:
            PREVIEWS.pop(k, None)
    return f"/api/stream/{token}"


@app.route("/api/stream/<token>")
def api_stream(token):
    url = PREVIEWS.get(token)
    if not url:
        abort(404)
    headers = {"User-Agent": BROWSER_UA}
    rng = request.headers.get("Range")
    if rng:
        headers["Range"] = rng
    try:
        upstream = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25)
    except Exception:
        abort(502)
    status = getattr(upstream, "status", 200) or 200
    passthru = {}
    for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
        v = upstream.headers.get(h)
        if v:
            passthru[h] = v
    passthru.setdefault("Accept-Ranges", "bytes")

    def gen():
        try:
            while True:
                chunk = upstream.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                upstream.close()
            except Exception:
                pass
    return Response(gen(), status=status, headers=passthru)


# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/version")
def api_version():
    # Used by the Chrome extension to detect when a newer extension ships.
    resp = jsonify({
        "extension_version": EXTENSION_VERSION,
        "ytdlp_current": current_ytdlp(),
    })
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/api/info", methods=["POST"])
def api_info():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, **EJS_OPTS}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"error": f"Could not read this URL: {e}"}), 400

    # collect a compact list of available qualities
    seen = set()
    formats = []
    for f in info.get("formats", []) or []:
        h = f.get("height")
        if h and f.get("vcodec") != "none" and h not in seen:
            seen.add(h)
            formats.append({"height": h, "fps": f.get("fps")})
    formats.sort(key=lambda x: x["height"], reverse=True)

    abr = sorted({int(f["abr"]) for f in info.get("formats", []) or []
                  if f.get("abr") and f.get("acodec") != "none"}, reverse=True)

    is_youtube = "youtube" in (info.get("extractor", "") or "").lower()
    media_kind, direct = _pick_preview(info)
    # YouTube uses its own iframe player; everyone else gets the proxied preview.
    preview_url = None if is_youtube else _register_preview(direct)

    return jsonify({
        "id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "duration": info.get("duration") or 0,
        "thumbnail": info.get("thumbnail"),
        "webpage_url": info.get("webpage_url", url),
        "video_qualities": formats,
        "source_audio_bitrates": abr,
        "is_youtube": is_youtube,
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "media_kind": media_kind,
        "preview_url": preview_url,
    })


@app.route("/api/process", methods=["POST"])
def api_process():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL"}), 400
    job_id = uuid.uuid4().hex[:12]
    set_job(job_id, status="queued", stage="Queued", progress=0,
            message="Waiting to start", files=[], error=None,
            title=data.get("title") or "clip")
    t = threading.Thread(target=run_job, args=(job_id, data), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def api_progress(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    return jsonify(job)


@app.route("/api/file/<job_id>/<path:fname>")
def api_file(job_id, fname):
    target = (OUT / job_id / fname).resolve()
    if not str(target).startswith(str((OUT / job_id).resolve())) or not target.exists():
        abort(404)
    return send_file(target, as_attachment=True, download_name=fname)


# ===================== BATCH: playlists / channels / many URLs ==============
BATCH = {}


def set_batch(bid, **kw):
    with JOBS_LOCK:
        BATCH.setdefault(bid, {})
        BATCH[bid].update(kw)


def get_batch(bid):
    with JOBS_LOCK:
        return dict(BATCH.get(bid, {}))


def _thumb(e):
    if e.get("thumbnail"):
        return e["thumbnail"]
    ts = e.get("thumbnails") or []
    return ts[-1].get("url") if ts else None


def _flat_entries(url, cap=200):
    """Quickly enumerate a playlist/channel (or pass through a single video)."""
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
            "skip_download": True, **EJS_OPTS}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("entries") is not None:
        items = []
        for e in info["entries"]:
            if not e:
                continue
            items.append({"url": e.get("url") or e.get("webpage_url") or e.get("id"),
                          "title": e.get("title") or "(untitled)",
                          "duration": e.get("duration"), "thumbnail": _thumb(e),
                          "uploader": e.get("uploader") or info.get("uploader") or info.get("title")})
            if len(items) >= cap:
                break
        return {"items": items}
    return {"items": [{"url": info.get("webpage_url") or url, "title": info.get("title"),
                       "duration": info.get("duration"), "thumbnail": _thumb(info),
                       "uploader": info.get("uploader")}]}


@app.route("/api/batch_info", methods=["POST"])
def api_batch_info():
    data = request.get_json(force=True)
    urls = data.get("urls")
    if isinstance(urls, str):
        urls = [urls]
    if not urls and data.get("url"):
        urls = [data["url"]]
    urls = [u.strip() for u in (urls or []) if u and u.strip()]
    if not urls:
        return jsonify({"error": "No URLs provided"}), 400
    items, errors, truncated = [], [], False
    CAP_TOTAL = 300
    for u in urls:
        try:
            items.extend(_flat_entries(u, cap=200)["items"])
        except Exception as e:
            errors.append({"url": u, "error": str(e)[:140]})
        if len(items) >= CAP_TOTAL:
            items, truncated = items[:CAP_TOTAL], True
            break
    seen, deduped = set(), []
    for it in items:
        k = it.get("url")
        if not k or k in seen:
            continue
        seen.add(k)
        deduped.append(it)
    return jsonify({"items": deduped, "count": len(deduped),
                    "truncated": truncated, "errors": errors})


@app.route("/api/batch_process", methods=["POST"])
def api_batch_process():
    data = request.get_json(force=True)
    items = data.get("items") or []
    if not items:
        return jsonify({"error": "No items selected"}), 400
    bid = uuid.uuid4().hex[:12]
    set_batch(bid, status="queued", done=0, total=len(items), zip=None, error=None,
              items=[{"title": it.get("title") or "item", "url": it.get("url"),
                      "status": "queued", "progress": 0, "file": None, "error": None}
                     for it in items])
    threading.Thread(target=run_batch, args=(bid, data), daemon=True).start()
    return jsonify({"batch_id": bid})


@app.route("/api/batch_progress/<bid>")
def api_batch_progress(bid):
    b = get_batch(bid)
    if not b:
        return jsonify({"error": "unknown batch"}), 404
    return jsonify(b)


def run_batch(bid, data):
    try:
        _run_batch(bid, data)
    except Exception as e:
        set_batch(bid, status="error", error=str(e))


def _run_batch(bid, data):
    items = data["items"]
    mode = data.get("mode", "audio")
    afmt = data.get("audioFormat", "mp3"); abr = str(data.get("audioBitrate", "192"))
    vfmt = data.get("videoFormat", "mp4"); vbr = str(data.get("videoBitrate", "original"))
    vquality = str(data.get("videoQuality", "best"))

    outdir = OUT / ("batch_" + bid)
    if outdir.exists():
        shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True)
    set_batch(bid, status="running")
    rows = get_batch(bid)["items"]
    produced = []

    for i, it in enumerate(items):
        rows[i]["status"] = "downloading"
        set_batch(bid, items=rows)

        def prog(p, i=i):
            rows[i]["progress"] = round(p, 1)
            set_batch(bid, items=rows)

        name = f"{i + 1:02d} - " + sanitize(it.get("title") or f"item{i + 1}")
        try:
            out = _fetch_and_convert(it["url"], name, mode, afmt, abr, vfmt, vbr, vquality, outdir, prog)
            rows[i].update(status="done", progress=100, file=out.name,
                           url=f"/api/file/batch_{bid}/{out.name}",
                           size=out.stat().st_size)
            produced.append(out)
        except Exception as e:
            rows[i].update(status="error", error=str(e)[:160])
        set_batch(bid, items=rows, done=i + 1)

    zurl, zsize = None, 0
    if produced:
        zip_path = outdir / "Stream Studio batch.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
            for p in produced:
                z.write(p, p.name)
        zurl, zsize = f"/api/file/batch_{bid}/{zip_path.name}", zip_path.stat().st_size
    set_batch(bid, status="done", zip=zurl, zip_size=zsize)


def _fetch_and_convert(url, title, mode, afmt, abr, vfmt, vbr, vquality, outdir, on_prog):
    """Download one full item and convert it (no clipping). Returns the output Path."""
    tmp = WORK / ("b_" + uuid.uuid4().hex[:8])
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        if mode == "audio":
            fmt, merge_fmt = "bestaudio/best", None
        else:
            fmt = (f"bestvideo[height<={vquality}]+bestaudio/best[height<={vquality}]/best"
                   if vquality.isdigit() else "bestvideo+bestaudio/best")
            merge_fmt = "mkv"

        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                on_prog((done / total * 90) if total else 0)
            elif d["status"] == "finished":
                on_prog(92)

        ydl_opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
                    "format": fmt, "outtmpl": str(tmp / "src.%(ext)s"),
                    "progress_hooks": [hook], **EJS_OPTS}
        if FFMPEG != "ffmpeg":
            ydl_opts["ffmpeg_location"] = str(Path(FFMPEG).parent)
        if merge_fmt:
            ydl_opts["merge_output_format"] = merge_fmt
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        source = next(iter(sorted(tmp.glob("src.*"))), None)
        if not source:
            raise RuntimeError("download produced no file")

        if mode == "audio":
            out = outdir / f"{title}.{afmt}"
            cmd = [FFMPEG, "-y", "-i", str(source), "-vn"]
            cmd += AUDIO_CODECS.get(afmt, AUDIO_CODECS["mp3"])
            if afmt not in LOSSLESS_AUDIO:
                cmd += ["-b:a", f"{abr}k"]
            cmd += [str(out)]
        else:
            out = outdir / f"{title}.{vfmt}"
            cmd = video_cmd(source, out, [], [], vfmt, vbr, True, afmt, abr)

        on_prog(95)
        proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {proc.stderr[-400:]}")
        on_prog(100)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
def run_job(job_id, data):
    try:
        _run_job(job_id, data)
    except Exception as e:
        set_job(job_id, status="error", error=str(e),
                stage="Failed", message=str(e))


def _run_job(job_id, data):
    url = data["url"].strip()
    mode = data.get("mode", "audio")            # audio | video | both
    merge = bool(data.get("merge", True))        # for "both"
    afmt = data.get("audioFormat", "mp3")
    abr = str(data.get("audioBitrate", "192"))
    vfmt = data.get("videoFormat", "mp4")
    vbr = str(data.get("videoBitrate", "original"))
    vquality = str(data.get("videoQuality", "best"))   # height or "best"
    regions = data.get("regions") or []
    title = sanitize(data.get("title") or "clip")

    jobdir = OUT / job_id
    if jobdir.exists():
        shutil.rmtree(jobdir, ignore_errors=True)
    jobdir.mkdir(parents=True)
    tmp = WORK / job_id
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)

    # ---- 1. download source ------------------------------------------------
    set_job(job_id, status="downloading", stage="Downloading from source",
            progress=0, message="Starting download")

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100) if total else 0
            spd = d.get("speed") or 0
            set_job(job_id, progress=round(pct, 1),
                    message=f"Downloading… {pct:4.1f}%  ({spd/1e6:.1f} MB/s)" if spd
                    else f"Downloading… {pct:4.1f}%")
        elif d["status"] == "finished":
            set_job(job_id, progress=100, message="Download finished, processing…")

    if mode == "audio":
        fmt = "bestaudio/best"
        merge_fmt = None
    else:
        if vquality.isdigit():
            fmt = f"bestvideo[height<={vquality}]+bestaudio/best[height<={vquality}]/best"
        else:
            fmt = "bestvideo+bestaudio/best"
        merge_fmt = "mkv"   # lossless container for the master, we re-encode later

    outtmpl = str(tmp / "source.%(ext)s")
    ydl_opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "format": fmt, "outtmpl": outtmpl, "progress_hooks": [hook],
        **EJS_OPTS,
    }
    if FFMPEG != "ffmpeg":
        ydl_opts["ffmpeg_location"] = str(Path(FFMPEG).parent)
    if merge_fmt:
        ydl_opts["merge_output_format"] = merge_fmt

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    duration = info.get("duration") or 0
    source = next(iter(sorted(tmp.glob("source.*"))), None)
    if not source:
        raise RuntimeError("Download produced no file")

    # ---- 2. build segment list --------------------------------------------
    segments = []
    if regions:
        for i, r in enumerate(regions):
            s = float(r.get("start", 0) or 0)
            e = float(r.get("end", duration) or duration)
            if e <= s:
                continue
            nm = sanitize(r.get("name") or f"region{i+1}")
            segments.append({"name": nm, "start": s, "end": e})
    if not segments:
        segments.append({"name": title, "start": 0, "end": duration})

    set_job(job_id, status="processing", stage="Encoding clips",
            progress=0, message=f"{len(segments)} segment(s) to encode")

    produced = []
    total_units = len(segments) * (2 if (mode == "both" and not merge) else 1)
    done_units = 0

    for seg in segments:
        base = f"{title} - {seg['name']}" if seg["name"] != title else title
        base = sanitize(base)
        ss = ["-ss", f"{seg['start']:.3f}"]
        seg_dur = (seg["end"] - seg["start"]) if seg["end"] else 0
        to = ["-t", f"{seg_dur:.3f}"] if seg_dur > 0 else []

        if mode == "audio":
            out = jobdir / f"{base}.{afmt}"
            cmd = [FFMPEG, "-y", *ss, "-i", str(source), *to, "-vn"]
            cmd += AUDIO_CODECS.get(afmt, AUDIO_CODECS["mp3"])
            if afmt not in LOSSLESS_AUDIO:
                cmd += ["-b:a", f"{abr}k"]
            cmd += [str(out)]
            run_ffmpeg(job_id, cmd, seg, done_units, total_units)
            produced.append(out)
            done_units += 1

        elif mode == "video":
            out = jobdir / f"{base}.{vfmt}"
            cmd = video_cmd(source, out, ss, to, vfmt, vbr, with_audio=True,
                            afmt=afmt, abr=abr)
            run_ffmpeg(job_id, cmd, seg, done_units, total_units)
            produced.append(out)
            done_units += 1

        else:  # both
            if merge:
                out = jobdir / f"{base}.{vfmt}"
                cmd = video_cmd(source, out, ss, to, vfmt, vbr, with_audio=True,
                                afmt=afmt, abr=abr)
                run_ffmpeg(job_id, cmd, seg, done_units, total_units)
                produced.append(out)
                done_units += 1
            else:
                vout = jobdir / f"{base} (video).{vfmt}"
                cmd = video_cmd(source, vout, ss, to, vfmt, vbr, with_audio=False,
                                afmt=afmt, abr=abr)
                run_ffmpeg(job_id, cmd, seg, done_units, total_units)
                produced.append(vout)
                done_units += 1

                aout = jobdir / f"{base} (audio).{afmt}"
                cmd = [FFMPEG, "-y", *ss, "-i", str(source), *to, "-vn"]
                cmd += AUDIO_CODECS.get(afmt, AUDIO_CODECS["mp3"])
                if afmt not in LOSSLESS_AUDIO:
                    cmd += ["-b:a", f"{abr}k"]
                cmd += [str(aout)]
                run_ffmpeg(job_id, cmd, seg, done_units, total_units)
                produced.append(aout)
                done_units += 1

    # ---- 3. package --------------------------------------------------------
    files = []
    for p in produced:
        files.append({"name": p.name, "size": p.stat().st_size,
                      "url": f"/api/file/{job_id}/{p.name}"})

    if len(produced) > 1:
        zip_path = jobdir / f"{title} (all).zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
            for p in produced:
                z.write(p, p.name)
        files.insert(0, {"name": zip_path.name, "size": zip_path.stat().st_size,
                         "url": f"/api/file/{job_id}/{zip_path.name}", "is_zip": True})

    shutil.rmtree(tmp, ignore_errors=True)
    set_job(job_id, status="done", stage="Complete", progress=100,
            message=f"Done — {len(produced)} file(s) ready", files=files)


def video_cmd(source, out, ss, to, vfmt, vbr, with_audio, afmt, abr):
    spec = VIDEO_CONTAINER.get(vfmt, VIDEO_CONTAINER["mp4"])
    cmd = [FFMPEG, "-y", *ss, "-i", str(source), *to]
    # video
    if vbr == "original":
        # try stream copy; if container/codec mismatch ffmpeg will still re-mux
        cmd += ["-c:v", spec["v"]]
    else:
        cmd += ["-c:v", spec["v"], "-b:v", f"{vbr}k"]
    # audio
    if with_audio:
        acodec = AUDIO_CODECS.get(afmt)
        # for video containers, use the container's native audio codec
        cmd += ["-c:a", spec["a"]]
        if afmt not in LOSSLESS_AUDIO:
            cmd += ["-b:a", f"{abr}k"]
    else:
        cmd += ["-an"]
    cmd += [str(out)]
    return cmd


def run_ffmpeg(job_id, cmd, seg, done_units, total_units):
    set_job(job_id, message=f"Encoding '{seg['name']}'…",
            progress=round(done_units / max(total_units, 1) * 100, 1))
    proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on '{seg['name']}':\n{proc.stderr[-800:]}")


def _make_tray_image():
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=14, fill=(124, 92, 255, 255))
    cx, cy, w = size * 0.54, size * 0.5, size * 0.2
    d.polygon([(cx - w * 0.8, cy - w), (cx - w * 0.8, cy + w), (cx + w, cy)], fill=(255, 255, 255, 255))
    return img


def _serve(port):
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


def _port_open(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    import webbrowser
    port = 5006
    autostart = "--autostart" in sys.argv  # launched at login -> stay quiet

    # Single instance: if the server is already running, just surface it.
    if _port_open(port):
        if not autostart:
            webbrowser.open(f"http://127.0.0.1:{port}")
        sys.exit(0)

    # Run the web server in the background.
    threading.Thread(target=_serve, args=(port,), daemon=True).start()

    # Open the UI once on a normal (manual) launch, but not on silent autostart.
    if not autostart:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    # System tray icon: lets the app run quietly with an explicit way to quit,
    # so there is no console window to accidentally close.
    try:
        import pystray
        from pystray import Menu, MenuItem

        # shared update state, filled by the background checker
        upd = {"available": False, "version": None, "busy": False}

        def _open(icon, item):
            webbrowser.open(f"http://127.0.0.1:{port}")

        def _quit(icon, item):
            icon.visible = False
            icon.stop()
            os._exit(0)

        def _do_update(icon, item):
            if upd["busy"] or not upd["available"]:
                return
            upd["busy"] = True
            try:
                icon.notify(f"Downloading yt-dlp {upd['version']}…", "Stream Studio")
                _, url = latest_ytdlp()
                if not url:
                    raise RuntimeError("no wheel url")
                install_ytdlp(url)
                icon.notify("Update installed. Restarting…", "Stream Studio")
                time.sleep(1.2)
                # relaunch quietly so the new yt-dlp is loaded from OVERRIDE_DIR
                args = [sys.executable] if FROZEN else [sys.executable, os.path.abspath(__file__)]
                args.append("--autostart")
                icon.visible = False
                os.execv(sys.executable, args)
            except Exception as e:
                upd["busy"] = False
                icon.notify(f"Update failed: {e}", "Stream Studio")

        def _update_text(item):
            if upd["busy"]:
                return "Updating…"
            if upd["available"]:
                return f"⬆ Update yt-dlp to {upd['version']}"
            return "yt-dlp is up to date"

        def _update_enabled(item):
            return upd["available"] and not upd["busy"]

        tray = pystray.Icon(
            "streamstudio", _make_tray_image(), "Stream Studio — running",
            menu=Menu(
                MenuItem("Open Stream Studio", _open, default=True),
                MenuItem(_update_text, _do_update, enabled=_update_enabled),
                MenuItem("Quit", _quit),
            ),
        )

        def _check_updates():
            # check shortly after launch, then once a day
            time.sleep(8)
            while True:
                try:
                    avail, latest = ytdlp_update_available()
                    if avail and not upd["available"]:
                        upd["available"], upd["version"] = True, latest
                        tray.update_menu()
                        tray.notify(
                            f"yt-dlp {latest} is available. Open the tray menu and click "
                            f"“Update yt-dlp” to install.", "Stream Studio update")
                except Exception:
                    pass
                time.sleep(24 * 3600)

        threading.Thread(target=_check_updates, daemon=True).start()
        tray.run()  # blocks until Quit
    except Exception:
        # No tray backend available -> keep the process alive serving.
        while True:
            time.sleep(3600)

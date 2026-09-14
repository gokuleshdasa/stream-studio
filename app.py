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
EXTENSION_VERSION = "1.2.0"  # version of the chrome-extension shipped with this app
APP_VERSION = "1.6.2"        # keep in sync with installer.iss AppVersion
GITHUB_REPO = "gokuleshdasa/stream-studio"

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

# Browser impersonation (via curl_cffi) so Cloudflare / anti-bot protected
# sites stop returning HTTP 403. Only enabled if a target is actually available
# in this build — otherwise left off so normal requests are never broken.
def _impersonate_opts():
    try:
        probe = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})
        targets = probe._get_available_impersonate_targets()
        if not targets:
            return {}
        norm = [(t[0] if isinstance(t, (list, tuple)) else t) for t in targets]
        chosen = next((t for t in norm if "chrome" in str(t).lower()), norm[0])
        # global target + tell the generic extractor to impersonate the webpage
        return {"impersonate": chosen,
                "extractor_args": {"generic": {"impersonate": [""]}}}
    except Exception:
        return {}
IMPERSONATE = _impersonate_opts()

# ---- user settings (cookies-from-browser, etc.) -----------------------------
# Persisted in the same user-writable folder as the yt-dlp override so it
# survives app updates / reinstalls.
SETTINGS_FILE = OVERRIDE_DIR.parent / "settings.json"
_SETTINGS_DEFAULTS = {
    # One of: "", "chrome", "edge", "firefox", "brave", "chromium", "opera",
    # "vivaldi", "safari". "" disables cookie loading.
    "cookies_from_browser": "",
    # Keep yt-dlp fresh automatically. Off by default is a footgun — YouTube
    # breaks the extractor every couple of weeks and 403s follow. On is what
    # end users actually want.
    "auto_update_ytdlp": True,
    # Same principle: keep the app itself fresh. Downloads the new installer
    # from GitHub Releases when a newer tagged version ships, then re-execs
    # via the silent installer once nothing is downloading.
    "auto_update_app": True,
}


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        data = {}
    out = dict(_SETTINGS_DEFAULTS)
    out.update({k: data.get(k, v) for k, v in _SETTINGS_DEFAULTS.items()})
    return out


def save_settings(patch):
    cur = load_settings()
    cur.update({k: patch[k] for k in patch if k in _SETTINGS_DEFAULTS})
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2)
    return cur


def cookie_opts():
    """yt-dlp options that pull cookies from a browser profile, if configured.

    Read fresh on each call so the user can change the setting without a
    restart. Bad values are silently ignored (yt-dlp would raise otherwise).
    """
    ALLOWED = {"chrome", "edge", "firefox", "brave", "chromium",
               "opera", "vivaldi", "safari"}
    who = (load_settings().get("cookies_from_browser") or "").strip().lower()
    if who in ALLOWED:
        return {"cookiesfrombrowser": (who,)}
    return {}


def base_ytdlp_opts():
    """Common yt-dlp options every call site should include: JS runtime,
    browser impersonation, and browser cookies (all optional / best-effort)."""
    return {**EJS_OPTS, **IMPERSONATE, **cookie_opts()}

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
    """Combined version endpoint. Fields:
       * extension_version / ytdlp_current  — legacy shape the Chrome extension polls.
       * ytdlp / latest / update_available / wheel / busy / last_error — used by
         the in-browser update banner.
    PyPI lookup is best-effort; a network failure leaves latest=null instead of
    breaking the response (extension check must never fail)."""
    cur = current_ytdlp()
    latest, wheel = None, None
    try:
        latest, wheel = latest_ytdlp()
    except Exception:
        pass
    update_available = bool(latest) and _ver_tuple(latest) > _ver_tuple(cur)
    # App update — best-effort, never blocks. Nightly builds skip this check
    # because their fabricated version tuple would appear ahead of GitHub.
    app_avail, app_latest, _app_url = False, None, None
    try:
        app_avail, app_latest, _app_url = app_update_available()
    except Exception:
        pass
    resp = jsonify({
        "extension_version": EXTENSION_VERSION,
        "ytdlp_current": cur,
        "ytdlp": cur,
        "latest": latest,
        "update_available": update_available,
        "wheel": wheel if update_available else None,
        "busy": _UPDATE_STATE["busy"],
        "last_error": _UPDATE_STATE["last_error"],
        # App self-update fields
        "app_version": APP_VERSION,
        "app_latest": app_latest,
        "app_update_available": app_avail,
        "app_update_busy": _APP_UPDATE_STATE["busy"],
        "app_update_error": _APP_UPDATE_STATE["last_error"],
    })
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/api/update_app", methods=["POST"])
def api_update_app():
    """Download the newest GitHub release installer and, once no jobs are
    active, silently run it — the installer closes this process, replaces
    the exe, and re-launches with --autostart. Returns immediately."""
    with _APP_UPDATE_LOCK:
        if _APP_UPDATE_STATE["busy"]:
            return jsonify({"status": "busy"}), 202
        _APP_UPDATE_STATE["busy"] = True
        _APP_UPDATE_STATE["last_error"] = None

    def worker():
        try:
            _, url = latest_app_release()
            if not url:
                raise RuntimeError("no StreamStudio-Setup.exe asset on the latest release")
            installer = _download_installer(url)
            _APP_UPDATE_STATE["downloaded"] = str(installer)
            # Wait for downloads to finish, then re-exec via installer.
            while _has_active_jobs():
                time.sleep(3)
            _launch_installer_and_exit(installer)
        except Exception as e:
            _APP_UPDATE_STATE["last_error"] = str(e)[:200]
        finally:
            _APP_UPDATE_STATE["busy"] = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"status": "started"})


# Cache of which URLs are handled by a dedicated extractor (browser button uses this).
_SUPPORT_CACHE = {}
_EXTRACTORS = None


def _url_supported(u):
    global _EXTRACTORS
    if not u or not re.match(r"^https?://", u):
        return False
    if u in _SUPPORT_CACHE:
        return _SUPPORT_CACHE[u]
    ok = False
    try:
        if _EXTRACTORS is None:
            from yt_dlp.extractor import gen_extractor_classes
            _EXTRACTORS = [ie for ie in gen_extractor_classes()
                           if (ie.IE_NAME or "").lower() != "generic"]
        for ie in _EXTRACTORS:
            try:
                if ie.suitable(u):
                    ok = True
                    break
            except Exception:
                pass
    except Exception:
        ok = False
    if len(_SUPPORT_CACHE) > 500:
        _SUPPORT_CACHE.clear()
    _SUPPORT_CACHE[u] = ok
    return ok


# ---- version / update / settings endpoints ---------------------------------
_UPDATE_STATE = {"busy": False, "last_error": None}
_UPDATE_LOCK = threading.Lock()

# App self-update state (separate lock from yt-dlp updater so they can run in
# parallel without contending — yt-dlp updates in-memory, app update replaces
# the exe itself, so serialising them adds no safety).
_APP_UPDATE_STATE = {"busy": False, "last_error": None, "downloaded": None}
_APP_UPDATE_LOCK = threading.Lock()


def latest_app_release():
    """Return (tag_without_v, setup_download_url) for the newest GitHub release.
    Raises on network failure — callers should catch."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
        headers={"User-Agent": "StreamStudio-Updater", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    tag = (data.get("tag_name") or "").lstrip("vV")
    setup_url = None
    for a in data.get("assets") or []:
        if (a.get("name") or "").lower() == "streamstudio-setup.exe":
            setup_url = a.get("browser_download_url")
            break
    return tag, setup_url


def app_update_available():
    try:
        tag, url = latest_app_release()
        return (bool(tag) and _ver_tuple(tag) > _ver_tuple(APP_VERSION)), tag, url
    except Exception:
        return False, None, None


def _download_installer(url):
    """Fetch the setup exe to a stable temp path. Returns the local Path."""
    req = urllib.request.Request(url, headers={"User-Agent": "StreamStudio-Updater"})
    dst = Path(tempfile.gettempdir()) / "StreamStudio-Setup-latest.exe"
    with urllib.request.urlopen(req, timeout=600) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f)
    return dst


def _launch_installer_and_exit(installer_path):
    """Spawn the silent installer detached and quit — the installer will close
    the current process cleanly if it needs to, replace files, then use the
    [Run] section in installer.iss to re-launch with --autostart."""
    args = [str(installer_path),
            "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            "/TASKS=startup,desktopicon"]
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so it survives our exit.
    DETACHED = 0x00000008 | 0x00000200
    subprocess.Popen(args, close_fds=True, creationflags=DETACHED | NO_WINDOW)
    time.sleep(0.5)
    os._exit(0)


@app.route("/api/update_ytdlp", methods=["POST"])
def api_update_ytdlp():
    """Kick off a background yt-dlp update using the same OVERRIDE_DIR path
    the tray menu uses. Returns immediately; poll /api/version for progress."""
    with _UPDATE_LOCK:
        if _UPDATE_STATE["busy"]:
            return jsonify({"status": "busy"}), 202
        _UPDATE_STATE["busy"] = True
        _UPDATE_STATE["last_error"] = None

    def worker():
        try:
            _, url = latest_ytdlp()
            if not url:
                raise RuntimeError("no wheel url on PyPI")
            install_ytdlp(url)
            # New yt_dlp is on disk but the current process still holds the
            # old one in memory. Flag it so the UI can prompt for a restart.
            _UPDATE_STATE["last_error"] = None
        except Exception as e:
            _UPDATE_STATE["last_error"] = str(e)[:200]
        finally:
            _UPDATE_STATE["busy"] = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.get_json(force=True) or {}
        cur = save_settings(data)
    else:
        cur = load_settings()
    return jsonify(cur)


@app.route("/api/supported")
def api_supported():
    # The browser extension calls this for the current page; if a dedicated
    # extractor handles it, the on-page download button appears.
    u = (request.args.get("u") or "").strip()
    resp = jsonify({"supported": _url_supported(u)})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/api/info", methods=["POST"])
def api_info():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, **base_ytdlp_opts()}
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


@app.route("/api/quickdownload", methods=["POST", "OPTIONS"])
def api_quickdownload():
    # Fire-and-forget whole-file download for the browser extension (IDM-style).
    if request.method == "OPTIONS":
        return _cors(jsonify({}))
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return _cors(jsonify({"error": "No URL"})), 400
    kind = (data.get("kind") or "video").lower()
    job_id = uuid.uuid4().hex[:12]
    jobdata = {
        "url": url, "title": data.get("title") or "media",
        "mode": "audio" if kind == "audio" else "video",
        "audioFormat": "mp3", "audioBitrate": "192",
        "videoFormat": "mp4", "videoBitrate": "original",
        "videoQuality": "best", "regions": [],
    }
    if data.get("headers"):
        jobdata["http_headers"] = data["headers"]
    set_job(job_id, status="queued", stage="Queued", progress=0,
            message="Queued", files=[], error=None, title=jobdata["title"])
    threading.Thread(target=run_job, args=(job_id, jobdata), daemon=True).start()
    return _cors(jsonify({"job_id": job_id}))


def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


def _ext_from(url, ctype):
    m = re.search(r"\.([a-z0-9]{2,5})(?:\?|#|$)", url, re.I)
    if m:
        return m.group(1).lower()
    ct = (ctype or "").split(";")[0].strip().lower()
    return {"audio/mpeg": "mp3", "audio/mp4": "m4a", "video/mp4": "mp4",
            "video/webm": "webm", "image/jpeg": "jpg", "image/png": "png",
            "image/gif": "gif", "image/webp": "webp"}.get(ct, "bin")


def _grab_one(url, title, headers, outdir, idx):
    """Download a single item to outdir. Streaming -> yt-dlp; else direct fetch
    (with the caller-supplied cookies/UA/Referer)."""
    name = f"{idx:02d} - " + sanitize(title or "file")
    if re.search(r"\.(m3u8|mpd)(\?|#|$)", url, re.I):
        out = outdir / f"{name}.mp4"
        ydl_opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
                    "outtmpl": str(out.with_suffix("")) + ".%(ext)s",
                    "merge_output_format": "mp4", **base_ytdlp_opts()}
        if FFMPEG != "ffmpeg":
            ydl_opts["ffmpeg_location"] = str(Path(FFMPEG).parent)
        if headers:
            ydl_opts["http_headers"] = headers
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
        got = next(iter(sorted(outdir.glob(name + ".*"))), None)
        return got or out
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=90) as r:
        blob = r.read()
        ext = _ext_from(url, r.headers.get("Content-Type"))
    out = outdir / f"{name}.{ext}"
    out.write_bytes(blob)
    return out


@app.route("/api/zipbundle", methods=["POST", "OPTIONS"])
def api_zipbundle():
    # Download a chosen set of media (with the page cookies) and zip them.
    if request.method == "OPTIONS":
        return _cors(jsonify({}))
    data = request.get_json(force=True)
    items = data.get("items") or []
    headers = data.get("headers") or {}
    want_zip = bool(data.get("zip", True))
    if not items:
        return _cors(jsonify({"error": "No items"})), 400
    job_id = uuid.uuid4().hex[:12]
    set_batch(job_id, status="running", done=0, total=len(items), zip=None, error=None,
              items=[{"title": it.get("title") or "file", "url": it.get("url"),
                      "status": "queued", "progress": 0, "file": None, "error": None}
                     for it in items])

    def work():
        outdir = OUT / ("bundle_" + job_id)
        if outdir.exists():
            shutil.rmtree(outdir, ignore_errors=True)
        outdir.mkdir(parents=True)
        rows = get_batch(job_id)["items"]
        produced = []
        for i, it in enumerate(items):
            rows[i]["status"] = "downloading"; set_batch(job_id, items=rows)
            try:
                out = _grab_one(it["url"], it.get("title"), headers, outdir, i + 1)
                rows[i].update(status="done", progress=100, file=out.name,
                               url=f"/api/file/bundle_{job_id}/{out.name}", size=out.stat().st_size)
                produced.append(out)
            except Exception as e:
                rows[i].update(status="error", error=str(e)[:160])
            set_batch(job_id, items=rows, done=i + 1)
        zurl, zsize = None, 0
        if produced and want_zip:
            zp = outdir / "Stream Studio downloads.zip"
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:
                for p in produced:
                    z.write(p, p.name)
            zurl, zsize = f"/api/file/bundle_{job_id}/{zp.name}", zp.stat().st_size
        set_batch(job_id, status="done", zip=zurl, zip_size=zsize)

    threading.Thread(target=work, daemon=True).start()
    return _cors(jsonify({"batch_id": job_id}))


@app.route("/api/progress/<job_id>")
def api_progress(job_id):
    job = get_job(job_id)
    if not job:
        return _cors(jsonify({"error": "unknown job"})), 404
    return _cors(jsonify(job))


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
            "skip_download": True, **base_ytdlp_opts()}
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
        return _cors(jsonify({"error": "unknown batch"})), 404
    return _cors(jsonify(b))


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
                    "progress_hooks": [hook], **base_ytdlp_opts()}
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
        **base_ytdlp_opts(),
    }
    if FFMPEG != "ffmpeg":
        ydl_opts["ffmpeg_location"] = str(Path(FFMPEG).parent)
    if merge_fmt:
        ydl_opts["merge_output_format"] = merge_fmt
    if data.get("http_headers"):
        ydl_opts["http_headers"] = data["http_headers"]

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


# ---- silent yt-dlp auto-updater --------------------------------------------
# Runs regardless of whether the tray backend loaded; the tray hooks into
# _UPDATE_STATE so the menu item reflects live status without duplicating work.
_active_relaunch_pending = threading.Event()


def _has_active_jobs():
    """True if a download / batch is currently in flight — auto-restart waits."""
    with JOBS_LOCK:
        for j in JOBS.values():
            if j.get("status") in ("queued", "downloading", "processing"):
                return True
        for b in BATCH.values():
            if b.get("status") in ("queued", "running"):
                return True
    return False


def _relaunch_when_idle(notify=None):
    """Wait for all downloads to finish, then re-exec so the new yt-dlp is
    actually loaded in memory. Safe no-op on the first startup path where the
    caller has already imported the fresh module from OVERRIDE_DIR."""
    _active_relaunch_pending.set()
    while _has_active_jobs():
        time.sleep(3)
    if callable(notify):
        try:
            notify()
        except Exception:
            pass
    time.sleep(0.8)  # let the notification surface before the flash
    args = [sys.executable] if FROZEN else [sys.executable, os.path.abspath(__file__)]
    args.append("--autostart")  # silent relaunch — user does not see a new tab
    try:
        os.execv(sys.executable, args)
    except Exception:
        # execv can fail on some Windows shells; fall back to spawn + exit.
        subprocess.Popen(args, close_fds=True, creationflags=NO_WINDOW)
        os._exit(0)


def ytdlp_autoupdater(interval_hours=6, tray_notify=None):
    """Background worker: check PyPI on start, then every `interval_hours`.
    Installs new versions silently into OVERRIDE_DIR and, once no jobs are
    active, re-execs the process so they take effect. Skips work entirely
    if the setting is off."""
    # Small initial delay so the network check doesn't fight cold-start CPU.
    time.sleep(6)
    while True:
        try:
            if load_settings().get("auto_update_ytdlp", True):
                with _UPDATE_LOCK:
                    busy = _UPDATE_STATE["busy"]
                if not busy:
                    avail, latest = ytdlp_update_available()
                    if avail and latest:
                        with _UPDATE_LOCK:
                            _UPDATE_STATE["busy"] = True
                            _UPDATE_STATE["last_error"] = None
                        try:
                            _, url = latest_ytdlp()
                            if url:
                                install_ytdlp(url)
                                # Fire-and-forget: relaunch once quiet. This
                                # thread returns immediately, but the relaunch
                                # thread will block until all jobs finish.
                                def _notify():
                                    if callable(tray_notify):
                                        tray_notify(f"yt-dlp updated to {latest}. Restarting…")
                                threading.Thread(
                                    target=_relaunch_when_idle,
                                    kwargs={"notify": _notify},
                                    daemon=True,
                                ).start()
                        except Exception as e:
                            with _UPDATE_LOCK:
                                _UPDATE_STATE["last_error"] = str(e)[:200]
                        finally:
                            with _UPDATE_LOCK:
                                _UPDATE_STATE["busy"] = False
        except Exception:
            # never let this thread die — a transient network hiccup is fine
            pass

        # ---- App self-update ----------------------------------------------
        # Runs from the same loop but under its own lock; a failed check does
        # not affect the yt-dlp path above. The app update replaces the exe,
        # so we do it AFTER the yt-dlp cycle to avoid discarding a fresh
        # yt-dlp install we just made.
        try:
            if load_settings().get("auto_update_app", True):
                with _APP_UPDATE_LOCK:
                    app_busy = _APP_UPDATE_STATE["busy"]
                if not app_busy:
                    avail, tag, url = app_update_available()
                    if avail and url:
                        with _APP_UPDATE_LOCK:
                            _APP_UPDATE_STATE["busy"] = True
                            _APP_UPDATE_STATE["last_error"] = None

                        def _app_worker(_tag=tag, _url=url):
                            try:
                                if callable(tray_notify):
                                    tray_notify(f"Downloading Stream Studio {_tag}…")
                                installer = _download_installer(_url)
                                _APP_UPDATE_STATE["downloaded"] = str(installer)
                                while _has_active_jobs():
                                    time.sleep(5)
                                if callable(tray_notify):
                                    tray_notify(f"Installing Stream Studio {_tag}…")
                                time.sleep(0.8)
                                _launch_installer_and_exit(installer)
                            except Exception as e:
                                _APP_UPDATE_STATE["last_error"] = str(e)[:200]
                            finally:
                                _APP_UPDATE_STATE["busy"] = False
                        threading.Thread(target=_app_worker, daemon=True).start()
        except Exception:
            pass

        time.sleep(max(1, int(interval_hours)) * 3600)


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

    # Silent yt-dlp auto-updater — the primary defence against 403 errors when
    # YouTube changes their site. Runs in every mode (tray, headless, dev).
    # Tray, if loaded, will attach its notify callback below.
    _autoupd_thread_slot = {"tray": None}

    def _autoupd_notify(msg):
        cb = _autoupd_thread_slot["tray"]
        if cb:
            cb(msg)

    threading.Thread(
        target=ytdlp_autoupdater,
        kwargs={"interval_hours": 6, "tray_notify": _autoupd_notify},
        daemon=True,
    ).start()

    # Open the UI once on a normal (manual) launch, but not on silent autostart.
    # Wait until the server is actually accepting connections, otherwise the
    # browser can race Flask's startup and get "connection refused" (blank page)
    # or a half-served HTML whose /static/style.css request 404s -> unstyled UI.
    if not autostart:
        def _open_when_ready():
            deadline = time.time() + 20  # generous cold-start budget
            while time.time() < deadline:
                if _port_open(port):
                    # Extra beat so Flask's request thread pool is warm before
                    # the browser fires HTML + CSS + JS in parallel.
                    time.sleep(0.2)
                    webbrowser.open(f"http://127.0.0.1:{port}")
                    return
                time.sleep(0.15)
            # Fallback: server never came up; open anyway so the user sees the
            # browser error and can inspect it, rather than a silent no-op.
            webbrowser.open(f"http://127.0.0.1:{port}")
        threading.Thread(target=_open_when_ready, daemon=True).start()

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

        # Hand the tray notifier to the auto-updater so silent updates surface
        # a discreet toast ("yt-dlp updated to X. Restarting…").
        _autoupd_thread_slot["tray"] = lambda msg: tray.notify(msg, "Stream Studio")

        tray.run()  # blocks until Quit
    except Exception:
        # No tray backend available -> keep the process alive serving.
        while True:
            time.sleep(3600)

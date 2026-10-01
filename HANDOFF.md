# Stream Studio — Developer Handoff

> Read this first. It is meant to let a developer who has never seen the project
> understand, run, change, release and debug it. Last updated for **app 1.7.1 /
> extension 2.2.0** (2026-10-01).

## 1. What it is

A **local** media downloader/editor. A Python Flask server (`app.py`) runs on
`127.0.0.1:5006`, wraps **yt-dlp** (resolve/download from 1,800+ sites) and
**FFmpeg** (clip/convert), and serves a vanilla-JS single-page UI. A companion
**Chrome (MV3) extension** puts a Download button on videos and sends the page
or media URL to that local server. A tray icon keeps it running in the
background. Everything self-updates.

```
Browser UI (templates/index.html + static/app.js + static/style.css)
        │  HTTP, localhost only
Chrome extension ──► Flask app.py ──► yt-dlp (+ yt-dlp-ejs, curl_cffi, brotli)
 (content.js,           │             FFmpeg  (clip / convert)
  background.js)        │             Deno    (JS runtime for YouTube challenges)
                        └─ tray (pystray) · auto-updaters · single-instance guard
```

No cloud, no accounts, no telemetry. Outbound calls: the sites being downloaded,
PyPI (yt-dlp/yt-dlp-ejs version check + wheel), GitHub Releases API (app update),
and GitHub (yt-dlp's EJS solver script, fetched once).

## 2. Repository map

| Path | Purpose |
|---|---|
| `app.py` | **Everything backend** (≈1.7k lines): Flask routes, download/clip pipeline (`run_job`), batch, yt-dlp hot-swap override, **all three auto-updaters**, extension sync, cross-OS helpers, tray, `__main__` |
| `templates/index.html`, `static/app.js`, `static/style.css` | UI. Vanilla JS, no build step. Update banners + Settings dialog live in `app.js` (~l.710–880) |
| `chrome-extension/` | `manifest.json` (version!), `content.js` (hover button, pill, download-manager modal), `background.js` (media sniffing, context menu, downloads, **self-reload**), `popup.*` |
| `build.py` | **Cross-platform build + packaging** (the one script to run). |
| `installer.iss` | Inno Setup script (Windows installer; `AppVersion` must equal `APP_VERSION`) |
| `.github/workflows/release.yml` | CI: tag `v*` → build Win+macOS+Linux → GitHub Release |
| `update-and-rebuild.bat` | Windows convenience: upgrade pip deps, then `python build.py` |
| `requirements.txt` | Runtime + build deps |
| `CHANGELOG.md` | Human history; **CI copies the matching `## <version>` section into the release notes** |
| `BUILD.md`, `CONTRIBUTING.md`, `README.md`, `dist-readme.txt` | Docs. `dist-readme.txt` is shipped inside the Windows installer as "READ ME FIRST.txt" |
| `docs/index.html` | GitHub Pages landing site |
| `Start Stream Studio.bat/.sh`, `Enable Autostart.bat`, `Load Stream Studio Extension*.bat` | Source-mode helpers (Windows `.bat`, POSIX `.sh`) |
| `build_assets/` | `app.ico` (tracked); `ffmpeg[.exe]`, `deno[.exe]` are downloaded at build time and git-ignored |
| `StreamStudio.spec`, `YTStudioEditor.spec`, `build/`, `dist/`, `Setup/`, `work/`, `downloads/` | Local artifacts, git-ignored. `build.py` does not use the `.spec` files |

## 3. Where state lives (per user)

`DATA_DIR` (see `_data_dir()` in `app.py`):

| OS | Path |
|---|---|
| Windows | `%LOCALAPPDATA%\Stream Studio` |
| macOS | `~/Library/Application Support/Stream Studio` |
| Linux | `$XDG_DATA_HOME/stream-studio` (default `~/.local/share/stream-studio`) |

Contents: `settings.json` (auto-update toggles, cookies-from-browser), `pkgs/`
(hot-swapped `yt_dlp/`, `yt_dlp_ejs/`), `chrome-extension/` (auto-synced copy to
load in Chrome), `instance.lock` (POSIX), `update-stage/` + `apply-update.sh`
(only during a mac/Linux self-update). Finished downloads go to
`~/Downloads/Stream Studio` (frozen) or `./downloads` (source).
Uninstalling does not delete `DATA_DIR`.

## 4. The three update systems (the core of "always up to date")

All run from `ytdlp_autoupdater()` in `app.py` (thread, first run 6 s after
start, then every 6 h) unless noted. Both toggles are in `settings.json`.

### 4.1 yt-dlp + yt-dlp-ejs — hot swap, no reinstall
1. `latest_pypi()` reads PyPI JSON; newer than `current_ytdlp()`?
2. `install_ytdlp()` downloads the *universal* wheel and unzips `yt_dlp/` then
   `yt_dlp_ejs/` into `DATA_DIR/pkgs/`.
3. At import time `_OverrideFinder` (a `sys.meta_path` hook, `OVERRIDE_PKGS`)
   makes those folders win over the copy frozen in the exe.
4. `_relaunch_when_idle()` waits for zero active jobs, then re-execs with
   `--autostart`. If an override fails to import, both folders are deleted and
   the frozen copy is used (self-healing, see top of `app.py`).
Only **pure-Python** packages can be hot-swapped. `curl_cffi`, `brotli`,
FFmpeg, Deno are binaries → they ride app releases (§4.2).

### 4.2 The app itself — GitHub Releases
- `latest_app_release()` calls `releases/latest`, picks the asset named by
  `update_asset_name()`:
  - Windows `StreamStudio-Setup.exe` → run silently
    (`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`); Inno closes the exe, replaces
    files, relaunches via `[Run]` (`--autostart`).
  - macOS `StreamStudio-macos-<arm64|x64>.tar.gz`, Linux
    `StreamStudio-linux-<arm64|x64>.tar.gz` → extract to `update-stage/`, verify
    `StreamStudio/StreamStudio` exists, then `apply-update.sh` waits for our PID,
    `cp -a` over the install dir, relaunches. Needs the install dir to be
    user-writable (otherwise the banner shows the error; user updates manually).
- **Asset names are a contract** between `build.py`, `release.yml` and the
  updater. Don't rename them.
- Skipped for source checkouts (`not FROZEN`) and until the release actually has
  the asset for this OS (so no banner while CI is mid-upload).
- Updates wait for downloads to finish (`_has_active_jobs()`).
- Manual path: teal banner in the UI → `POST /api/update_app`.

### 4.3 The Chrome extension — files follow the app, extension reloads itself
Chrome will not auto-update an *unpacked* extension, but it will reload one.
1. `sync_extension()` (every app start, and on each `/api/extension` call)
   hashes the bundled `chrome-extension/` and mirrors it into
   `DATA_DIR/chrome-extension/` if different. **Users load that folder once.**
   (Windows installer also refreshes `C:\Program Files\Stream Studio\chrome-extension`.)
2. `background.js → selfUpdateCheck()` (wakes on any extension message, at most
   every 30 min, plus on browser start/install) fetches `GET /api/extension`
   and, if `version` > its own `manifest.version`, calls `chrome.runtime.reload()`.
   `reloadedFor` in `chrome.storage.local` prevents reload loops.
3. Bump **both** `chrome-extension/manifest.json` `"version"` and
   `EXTENSION_VERSION` in `app.py` whenever extension files change
   (`build.py` fails if they differ). If you forget to bump, running extensions
   won't reload.
Extensions older than 2.1.0 don't have step 2 — one manual reload is needed.

## 5. Cross-platform status

| Area | Windows | macOS | Linux |
|---|---|---|---|
| Run from source (`python app.py`) | ✅ tested | 🟡 written, untested | 🟡 written, untested |
| Frozen build | ✅ PyInstaller onedir + Inno (tested on every release) | 🟡 CI only | 🟡 CI only |
| Tray (pystray) | ✅ | 🟡 (needs main thread — it is) | 🟡 needs AppIndicator/GTK; falls back to headless loop |
| Single instance | named mutex | `flock` | `flock` |
| Autostart | installer shortcut / `--enable-autostart` (Run key) | `--enable-autostart` (LaunchAgent) | `--enable-autostart` (XDG .desktop) |
| App self-update | silent installer ✅ | tar.gz swap script 🟡 | tar.gz swap script 🟡 |
| yt-dlp / extension updates | ✅ | ✅ (pure Python) | ✅ |

🟡 = implemented carefully but **never run on that OS by the author**. First
real test = tag a release and download the artifacts (see §8 checklist).
Known gaps: no code signing/notarization (macOS Gatekeeper: right-click → Open,
or `xattr -dr com.apple.quarantine StreamStudio`); no `.app` bundle or `.deb`/
AppImage; Intel-Mac and Linux-arm64 builds need extra CI matrix entries
(`macos-13`/`ubuntu-24.04-arm`); Windows ARM not built.

### Extension compatibility
Chromium MV3 browsers — Chrome, Edge, Brave, Opera, Vivaldi — on Windows, macOS,
Linux (**Load unpacked**). Content script runs on all http(s) pages and frames;
the hover button is on by default (`extended !== false`), uses `position:fixed`,
detects media via `composedPath()`/`elementsFromPoint()`, and moves into the
fullscreen element. All calls to `127.0.0.1` go through `background.js`
(not the page origin) to avoid CORS/Local-Network-Access blocks.
**Not supported: Firefox** (needs `background.scripts` + a signed/temporary add-on;
Chrome rejects the extra manifest keys on older versions). Pages where a content
script cannot run: `chrome://`, Web Store, `file://` unless "Allow access to file URLs".
DRM (Widevine/EME) streams cannot be downloaded by yt-dlp — the button will fire
but the download fails.

## 6. HTTP API (localhost:5006)

`/` UI · `/api/info` (yt-dlp metadata) · `/api/process` + `/api/progress/<id>`
(download/clip job) · `/api/quickdownload` (extension, CORS) · `/api/zipbundle`
+ `/api/batch_progress/<id>` · `/api/supported?u=` · `/api/stream/<token>`
(Range-proxy preview) · `/api/version` (everything; does internet lookups) ·
`/api/extension` (fast, no lookups; used by the extension self-update) ·
`/api/open_extension_folder` · `/api/update_ytdlp` · `/api/update_app` ·
`/api/settings`. CLI flags: `--autostart` (quiet start), `--enable-autostart`,
`--disable-autostart`, `--print-extension-path`.

## 7. How to release (the procedure)

1. Make changes. Update `CHANGELOG.md` with a new top section `## X.Y.Z — date`
   (CI uses it as the release notes — heading must start with the exact version).
2. Bump versions — **three places must agree**:
   `APP_VERSION` (app.py) = `AppVersion` (installer.iss); and if extension
   changed: `EXTENSION_VERSION` (app.py) = manifest.json `version`.
   `python build.py --check` verifies.
3. Commit, push to `main`.
4. **Preferred:** `git tag vX.Y.Z && git push origin vX.Y.Z` → GitHub Actions
   builds Windows/macOS/Linux and publishes the release with all assets.
   Watch: Actions tab → *Release*. The in-app updaters pick it up within 6 h.
5. **Manual Windows-only fallback** (how 1.0–1.6.5 were released):
   `python build.py` → `Setup\StreamStudio-Setup.exe`, then
   `gh release create vX.Y.Z Setup/StreamStudio-Setup.exe --title "vX.Y.Z — …" --notes-file <notes>`.
   The asset **must** be named exactly `StreamStudio-Setup.exe`.
6. Verify: `gh release view vX.Y.Z`; install it over an old version and confirm
   the tray starts and `/api/version` shows the new `app_version`.

`/releases/latest` ignores pre-releases and drafts — don't mark real releases as such.

## 8. Test checklist (no automated test suite exists)

- `python app.py`, open the UI, paste a YouTube URL, download an MP3 and a
  clipped MP4.
- Extension: load folder from `StreamStudio --print-extension-path`; open a
  YouTube watch page; enable "Extended mode" in the popup; hover the video →
  Download button → click: browser tab opens Stream Studio with the URL
  (blob: sources route through the app; direct files download via the browser).
  Drag the button (position persists), ✕ hides it for that video only.
- Self-update of extension: lower `manifest.json` version locally, reload, wait
  or call `chrome.storage.local.set({lastSelfCheck:0})` in the SW console and
  wake it → it should reload into the newer version.
- yt-dlp swap: delete `DATA_DIR/pkgs`, start app, watch it appear within ~10 s
  and the app restart (needs a newer PyPI release than the bundled one).
- macOS/Linux first-run (when someone has the hardware): run the tarball,
  tray icon, `--enable-autostart`, then publish a higher tag and confirm the
  self-update swap.

## 9. Gotchas / lessons learned

- **Never `--onefile`.** It extracted ~350 MB to `%TEMP%` each launch; cleanup/AV
  deleted `static/` mid-run → unstyled pages (1.6.4). `--onedir` only.
- **Build outside OneDrive/Dropbox.** Sync clients lock `.dist-info\licenses`
  and PyInstaller dies. `build.py` builds in `C:\ss-build` (Win) or
  `$TMPDIR/ss-build`; override with `SS_BUILD_DIR`. Not under `%LOCALAPPDATA%`:
  Microsoft-Store Python virtualises AppData writes, so Inno Setup could not see
  the PyInstaller output (the build "succeeds" but ISCC finds no files).
- **`display:flex` on an element beats the `hidden` attribute.** Use
  `:not([hidden])` (1.6.3).
- **Pointer capture retargets `click`.** Calling `setPointerCapture` on
  `pointerdown` made the on-video Download label unclickable (fixed 1.7.0).
  Capture only after the drag threshold. Same applies to any draggable widget.
- A `blob:` video src (YouTube etc.) can't be fetched by the app — the hover
  button deliberately opens the app with the *page* URL instead (`openApp`).
- Don't add `alarms`/other permissions to the manifest casually: changing
  permissions of an already-loaded unpacked extension can disable it until the
  user re-approves. The self-update uses no new permission for this reason.
- Single-instance must stay deterministic: mutex/flock *then* port probe;
  auto-updater relaunches use `--autostart` so no extra browser tab opens.
- `FFMPEG` is the literal `"ffmpeg"` when not bundled (system PATH) — several
  call sites compare against that string.
- Line endings: files are LF in the repo; Git on Windows may warn about CRLF.

## 10. Ideas not done

macOS `.app`/dmg + notarization; Windows code signing (removes SmartScreen);
Linux AppImage; scheduled CI that rebuilds weekly to refresh bundled
ffmpeg/deno/curl_cffi; Chrome Web Store listing (would give real
auto-update without Developer mode); automated tests (pytest for `_ver_tuple`,
`update_asset_name`, `sync_extension`, a Playwright smoke test of the hover button).

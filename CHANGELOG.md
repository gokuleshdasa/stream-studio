# Stream Studio — Changelog

## 1.7.0 — 2026-10-01

Everything keeps itself up to date, and it now runs on Windows, macOS and Linux.
(Also contains the unreleased 1.6.6 fix below.)

**Chrome extension 2.0.2 → 2.1.0**
- **Fix: the on-video Download button did nothing.** The drag code captured the
  pointer on press, which retargeted the click away from the "Download" label
  (✕ worked only because the drag handler skips buttons). The pointer is now
  captured only after a real drag (>3 px) begins.
- **Self-updating.** Chrome cannot auto-update an *unpacked* extension, but it
  can reload one. The app keeps the extension files current; `background.js`
  asks `GET /api/extension` (fast, no internet lookups) at most every 30 min and
  calls `chrome.runtime.reload()` when the app ships a newer version. One
  reload per advertised version (loop guard). No new permissions.
  *Users on 2.0.x must reload the extension manually once to get this.*

**App 1.6.5 → 1.7.0**
- **New: always-current extension folder.** `sync_extension()` copies the bundled
  extension to a user-writable `DATA_DIR/chrome-extension` (hash-compared, at
  every start). Load *that* folder in Chrome. Tray → "Open Chrome extension
  folder", `GET /api/extension`, `POST /api/open_extension_folder`,
  `StreamStudio --print-extension-path`.
- **yt-dlp updates now also refresh `yt-dlp-ejs`** (the YouTube JS-challenge
  solver) via the same hot-swap override. Binary deps (curl_cffi, brotli,
  ffmpeg, deno) ride app releases. Override finder generalised to
  `OVERRIDE_PKGS = (yt_dlp, yt_dlp_ejs)`; self-heal removes both on failure.
- **Cross-platform runtime** (`app.py`): per-OS data dir (`DATA_DIR`), `ffmpeg`/
  `deno` name resolution without `.exe` + PATH fallback, POSIX single-instance
  lock (`flock`), `--enable-autostart` / `--disable-autostart` (Windows Run key,
  macOS LaunchAgent, Linux XDG autostart).
- **Cross-platform app self-update.** Windows unchanged (silent Inno installer).
  macOS/Linux download `StreamStudio-<macos|linux>-<arch>.tar.gz` from the latest
  release, verify it, and a small shell script swaps files after the process
  exits and relaunches. Banner only appears once the release actually carries
  an asset for this OS, and never for source checkouts (`git pull` instead).
- **New `build.py`**: one cross-platform build (version-sync check → ffmpeg/deno
  from `imageio-ffmpeg`/`deno` wheels if not in `build_assets/` → PyInstaller
  `--onedir` → Inno Setup or tar.gz). `update-and-rebuild.bat` now just refreshes
  deps and calls it.
- **New `.github/workflows/release.yml`**: pushing a `v*` tag builds all three
  OSes and publishes the release with notes taken from this file.
- **New `HANDOFF.md`** — full developer handoff. BUILD / CONTRIBUTING / README /
  READ ME FIRST rewritten to match reality.
- `Start Stream Studio.sh` for macOS/Linux source runs.
- macOS/Linux builds are **new and only exercised via CI**, not yet field-tested
  (see HANDOFF.md → "Known gaps").

## 1.6.6 — 2026-10-01 (git commit only; never built or released — shipped inside 1.7.0)

Fix: the Chrome extension's on-video Download button did nothing when clicked.

- **Hover button click works again.** The drag code captured the pointer on
  press, which retargeted the click away from the Download label. The pointer
  is now captured only once a real drag (>3px) starts.
- Extension version 2.0.2 → 2.0.3; app EXTENSION_VERSION mirror updated.
- installer AppVersion 1.6.5 → 1.6.6.

## 1.6.5 — 2026-09-24

Chrome extension: drag the button anywhere, close it per video.

- **Draggable pill and hover button.** Grab either button anywhere on its
  body and drag — the position saves to `chrome.storage.local` and
  persists across reloads. Kicks the ✕ / Download click through cleanly
  so a drag doesn't accidentally trigger the button.
- **Per-video hide.** ✕ on the pill hides it for **this page only**
  (persisted). ✕ on the hover button hides it for **this video only**
  (persisted). Different YouTube video → button comes back. Clears itself
  after 500 remembered videos so `chrome.storage` doesn't grow forever.
- **Hover button auto-position surrenders to your drag.** As soon as
  you've moved it once, Stream Studio stops fighting your placement —
  the button stays where you put it across scrolls, video switches, and
  page loads. Clear the `hoverPos` key in the extension's storage to
  restore auto-positioning.
- Extension version 2.0.1 → 2.0.2; app EXTENSION_VERSION mirror updated.
- installer AppVersion 1.6.4 → 1.6.5.

## 1.6.4 — 2026-09-20

Reliability: no more blank / unstyled pages, no more zombie duplicate
processes.

- **Switched PyInstaller build from `--onefile` to `--onedir`.** The old
  build extracted a ~350 MB payload to `%TEMP%\_MEIxxxxx\` on every launch;
  when Windows temp cleanup or antivirus touched a file mid-run, `static/`
  or `templates/` would vanish and Flask would silently 404 all CSS and JS
  — the page rendered as raw unstyled HTML. All runtime files now sit
  permanently next to the exe in `C:\Program Files\Stream Studio\_internal\`
  (what Chrome, VSCode, Slack, Postman all do). Nothing to lose mid-run.
- **Proper single-instance guard.** Replaced the port-open probe with a
  Windows named mutex (`StreamStudio-SingleInstance-Mutex-v1`). The port
  probe alone was racy — two launches within 0.4 s (Startup + tray click,
  or Startup + auto-updater re-exec) both saw an open port and both
  proceeded. Kernel mutex settles it deterministically.
- Installer bundles the whole `dist\StreamStudio\` folder now, not just
  the single exe.

## 1.6.3 — 2026-09-14

Single vs Batch — pruning the noise.

- **CSS bug:** `#batchInput` had `display:flex` on the id, which overrode
  the `hidden` attribute — so the "Paste links here" textarea and **Fetch
  list** button were visible on the Single tab. Same class of bug hit the
  update banners (`.upd-banner{display:flex}`). Both now use
  `:not([hidden]){display:flex}` so `hidden` actually hides them.
- **Chrome extension no longer double-buttons a video page.** The corner
  "Download" pill was showing on YouTube watch pages alongside the on-video
  hover button. The pill now only surfaces on **listing** URLs (channel,
  `/@handle`, `/playlist`, `/c/`, `/user/`, Vimeo channels, etc.). Single
  videos keep just the on-video hover button.
- **The pill sends a batch flag.** Clicking it on a channel page opens the
  app with `?u=…&batch=1`. The app switches to the Batch tab and
  auto-fetches the list — no more spinner spinning forever because a
  channel URL was fed into the single-item info endpoint.
- Extension version 2.0.0 → 2.0.1.

## 1.6.2 — 2026-09-14
**Stream Studio now self-updates itself, not just yt-dlp.** True zero-touch.

- Background thread also polls `GET
  api.github.com/repos/gokuleshdasa/stream-studio/releases/latest` on the
  same 6-hour cadence. Newer tag → downloads `StreamStudio-Setup.exe` to
  `%TEMP%` and, once no jobs are active, runs it silently
  (`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`). Inno Setup closes the running
  exe, replaces files, re-launches with `--autostart`.
- Tray toasts: "Downloading Stream Studio X.Y.Z…", "Installing Stream Studio
  X.Y.Z…". No dialog.
- Web-UI teal **"Install & restart"** banner is the manual fallback.
- Settings dialog adds a toggle: **Keep Stream Studio itself up to date
  automatically** (default on). Persisted alongside the yt-dlp toggle.
- New endpoint `POST /api/update_app` mirrors `/api/update_ytdlp`.
- `/api/version` now also returns `app_version`, `app_latest`,
  `app_update_available`.

## 1.6.1 — 2026-09-14
Bug fix: `/api/version` route was defined twice after the 1.6.0 refactor, so
the app failed to start on fresh installs with `AssertionError: View function
mapping is overwriting an existing endpoint function`. Merged into one route
that returns both the legacy `extension_version` / `ytdlp_current` fields the
Chrome extension expects and the new `latest` / `update_available` / `busy`
fields the in-browser update banner reads.

## 1.6.0 — 2026-09-14
**Zero-touch yt-dlp updates.** Every YouTube-extractor breakage should now
self-heal without any user action.

- Background auto-updater checks PyPI on startup and every 6 hours. When a
  newer yt-dlp ships, it downloads the wheel to `%LOCALAPPDATA%\Stream
  Studio\pkgs\yt_dlp` and, once no downloads are running, silently re-execs
  the app so the new version is loaded in memory.
- Tray toast: "yt-dlp updated to X. Restarting…" when this happens. No
  dialog, no confirmation.
- Web-UI banner as a manual fallback: pink "Update now" card if PyPI is
  reachable but the auto-updater is disabled or an install failed.
- Settings dialog (⚙ in the top bar):
    - Toggle **auto-update yt-dlp** (default on).
    - Dropdown **load cookies from browser** (chrome / edge / firefox /
      brave / chromium / opera / vivaldi). Fixes age-gated, region-locked,
      member-only, and login-required videos.
- Cookies-from-browser is threaded through every yt-dlp call site
  (`/api/info`, `/api/process`, batch, playlist enumerator, HLS grabber) via
  a single `base_ytdlp_opts()` helper that merges impersonation + JS runtime
  + cookies. Changing the cookie source takes effect on the next download —
  no restart needed.
- Startup race fixed: browser now opens only once Flask is actually
  listening, so cold launches no longer show a blank or unstyled page.
- `Start Stream Studio.bat` port banner corrected (5001 → 5006).
- New `Enable Autostart.bat` for source-mode users who want the app to
  launch silently at login without going through the installer.
- Bundled companions: `yt-dlp-ejs`, `brotli`, `curl_cffi` are now
  `--collect-all`ed into the exe, so YouTube's JS challenge solver and
  browser impersonation work without extra `pip install`s.
- `requirements.txt` pins `yt-dlp>=2026.8.30` plus the three companions.

# Stream Studio — Changelog

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

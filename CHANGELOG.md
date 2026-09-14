# Stream Studio — Changelog

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

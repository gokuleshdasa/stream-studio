<div align="center">

# 🎛️ Stream Studio

### Download, clip, convert & re-encode media from **any** site — locally, with an ultra-modern UI.

[![License: MIT](https://img.shields.io/badge/License-MIT-7c5cff.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-19d3da.svg)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-ffb020.svg)](https://www.python.org/)
[![Engine: yt-dlp + FFmpeg](https://img.shields.io/badge/engine-yt--dlp%20%2B%20FFmpeg-ff5ca8.svg)](https://github.com/yt-dlp/yt-dlp)

Paste a link from **YouTube, SoundCloud, Vimeo, Dailymotion, Bandcamp, Twitch** and 1,800+ other sites. Stream Studio fetches the media, lets you mark named clips on a **timeline with live preview**, and exports the exact audio/video, format and bitrate you want — all on your machine.

</div>

---

## ✨ Features

- **Any site** — anything [yt-dlp](https://github.com/yt-dlp/yt-dlp) supports (1,800+).
- **Live preview for every source** — a built-in streaming proxy feeds an HTML5 player, so you can scrub and preview clips even on non-YouTube sites. YouTube uses its native player.
- **Timeline editor** — drag to mark named regions, trim the edges, preview just that region.
- **Audio**: MP3, WAV, AAC, M4A, FLAC, Opus, OGG · **Video**: MP4, MKV, WebM, with full bitrate control.
- **Smart, friendly fallback** — if a source can't be previewed or clipped (HLS-only, no duration, etc.), the UI adapts and a gentle toast tells you the next step. No confusion.
- **Runs in the background** — a system-tray service that auto-starts at login.
- **Keeps itself up to date, silently** — `yt-dlp` and its YouTube solver (`yt-dlp-ejs`) hot-swap from PyPI every 6 h; the app itself updates from GitHub Releases; the Chrome extension reloads itself when the app ships a newer one. Each self-heals if an update fails.
- **Windows, macOS and Linux.**
- **Bundled everything** — Python, FFmpeg, yt-dlp, and a Deno JS runtime in one package.
- **Chrome extension** — IDM-style Download button on videos (draggable, closable per video), right-click download manager, send any page to the app.

## 🚀 Install (end users)

Grab the latest build from the [Releases](../../releases) page:

| OS | File | Notes |
|---|---|---|
| Windows 10/11 | `StreamStudio-Setup.exe` | SmartScreen may warn (unsigned) → **More info → Run anyway**. Auto-starts at login. |
| macOS | `StreamStudio-macos-arm64.tar.gz` | Unpack, then right-click → Open the first time (unsigned). *New, community-testing.* |
| Linux | `StreamStudio-linux-x64.tar.gz` | Unpack and run `./StreamStudio`. Tray needs AppIndicator/GTK, otherwise runs headless. *New, community-testing.* |

On macOS/Linux enable start-at-login with `./StreamStudio --enable-autostart`.
The app opens at <http://127.0.0.1:5006>; files go to `Downloads/Stream Studio`.

### Chrome extension (load once, then it follows the app)

1. Tray icon → **Open Chrome extension folder** (or run `StreamStudio --print-extension-path`).
2. `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → pick that folder.

The app keeps that folder current and the extension reloads itself when a newer
version is available. Chrome can't auto-update unpacked extensions on its own —
this is how Stream Studio works around it (details in [HANDOFF.md](HANDOFF.md) §4.3).

## 🛠️ Run from source

```bash
git clone https://github.com/gokuleshdasa/stream-studio.git
cd stream-studio
pip install -r requirements.txt
python app.py
```

Requires [FFmpeg](https://ffmpeg.org/) on `PATH` (`python build.py` can fetch one). Opens at <http://127.0.0.1:5006>. On macOS/Linux use `./"Start Stream Studio.sh"`.

## 🏗️ Build the installer

`python build.py` builds for your OS; pushing a `v*` tag builds all three in CI and publishes the release. See **[BUILD.md](BUILD.md)**. Developers: read **[HANDOFF.md](HANDOFF.md)** first.

## 🧩 How it works

```
Browser UI (HTML/CSS/JS)  ──HTTP──►  Flask backend (app.py)
        ▲     ▲                            │
        │     └─ /api/stream  ◄────────────┤  proxied preview (Range-enabled)
   Chrome extension                        ├─ yt-dlp  → resolve + download (any site)
                                           ├─ FFmpeg  → clip / convert / re-encode
                                           └─ Deno    → JS challenge solving
                                           tray service + self-updater
```

| Layer | Tech |
|---|---|
| UI | Vanilla HTML / CSS / JS (glassmorphism, draggable timeline, adaptive states) |
| Backend | Python + Flask + a Range-aware streaming proxy |
| Download | [yt-dlp](https://github.com/yt-dlp/yt-dlp) (self-updating) |
| Media | [FFmpeg](https://ffmpeg.org/) |
| JS runtime | [Deno](https://deno.com/) |
| Packaging | PyInstaller (`--onedir`) + Inno Setup (Windows) / tar.gz (macOS, Linux), GitHub Actions |

## ⚖️ Legal & responsible use

For downloading content **you own or have the right to use** (your own uploads, Creative Commons, content with permission, etc.). Downloading copyrighted material may violate a site's Terms of Service and local law. **You are responsible for how you use it.** Provided for educational and personal use, with no liability for misuse.

## 🙏 Credits

Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp), [FFmpeg](https://ffmpeg.org/), [Flask](https://flask.palletsprojects.com/), and [Deno](https://deno.com/).

## 📄 License

[MIT](LICENSE) © 2026 Gokul Esh Dasa

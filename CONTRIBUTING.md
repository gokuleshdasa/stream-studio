# Contributing to Stream Studio

Thanks for your interest! Start with **[HANDOFF.md](HANDOFF.md)** — architecture,
update systems, release procedure and gotchas in one place.

## Getting started

1. Fork and clone the repo.
2. `pip install -r requirements.txt`
3. FFmpeg on your `PATH` (or let `python build.py` fetch one into `build_assets/`).
4. `python app.py` (Windows) / `./"Start Stream Studio.sh"` (macOS, Linux) →
   <http://127.0.0.1:5006>.
5. Chrome extension: `python app.py --print-extension-path`, then
   `chrome://extensions` → Developer mode → **Load unpacked** → that folder.

## Project layout

| Path | What |
|---|---|
| `app.py` | Flask backend, job pipeline, yt-dlp override, all auto-updaters, tray, cross-OS helpers |
| `templates/index.html`, `static/app.js`, `static/style.css` | Vanilla-JS UI |
| `chrome-extension/` | MV3 extension (`content.js`, `background.js`, `popup.*`) |
| `build.py`, `installer.iss`, `.github/workflows/release.yml` | Build / package / release |
| `CHANGELOG.md`, `BUILD.md`, `HANDOFF.md` | History, build how-to, developer handoff |

## Guidelines

- Keep the UI dependency-free (vanilla JS/CSS) unless there is a strong reason.
- Match the existing code style; keep Windows, macOS and Linux working (use
  `IS_WIN` / `IS_MAC`, `DATA_DIR`, `EXE_SUFFIX`; never hard-code `.exe` or `\`).
- Changed anything under `chrome-extension/`? Bump **both** manifest `version`
  and `EXTENSION_VERSION` in `app.py` — that is what makes installed extensions
  reload themselves. `python build.py --check` verifies versions.
- Add a `CHANGELOG.md` entry for user-visible changes.
- Test a real conversion (audio clip + a video clip) and, for extension work,
  the hover button on a YouTube page before opening a PR.
- One focused change per PR; describe what and why.

## Reporting issues

Open an issue with: OS version, what you did, what you expected, what happened,
and any error text from the tray/console.

## Scope & responsible use

This project is for downloading content you have the right to use. Please don't
file requests aimed at circumventing platform rules or enabling infringement.

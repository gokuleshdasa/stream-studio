# Contributing to Stream Studio

Thanks for your interest! Contributions are welcome.

## Getting started

1. Fork and clone the repo.
2. `pip install -r requirements.txt`
3. Make sure `ffmpeg` is on your `PATH`.
4. `python app.py` and open <http://127.0.0.1:5001>.

## Project layout

| Path | What |
|---|---|
| `app.py` | Flask backend: info, download, clip/convert pipeline, tray + self-updater |
| `templates/index.html` | Single-page UI |
| `static/app.js` | Frontend logic + timeline editor |
| `static/style.css` | Styling |
| `chrome-extension/` | Companion MV3 extension |
| `installer.iss` | Inno Setup installer script |
| `BUILD.md` | How to produce the exe + installer |

## Guidelines

- Keep the UI dependency-free (vanilla JS/CSS) unless there's a strong reason.
- Match the existing code style.
- Test a real conversion (audio clip + a video clip) before opening a PR.
- One focused change per PR; describe what and why.

## Reporting issues

Open an issue with: OS version, what you did, what you expected, what happened, and any error text from the tray/console.

## Scope & responsible use

This project is for downloading content you have the right to use. Please don't file requests aimed at circumventing platform rules or enabling infringement.

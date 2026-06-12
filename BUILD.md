# Building Stream Studio

The repository ships **source only**. The large third-party binaries (FFmpeg ~140 MB, Deno ~96 MB) are downloaded at build time and are git-ignored.

## Prerequisites

- Windows 10/11 (x64)
- Python 3.10+
- [Inno Setup 6](https://jrsoftware.org/isdl.php) (for the installer)

```bash
pip install -r requirements.txt
```

## 1. Fetch the bundled binaries

Place these inside `build_assets/`:

| File | Where to get it |
|---|---|
| `build_assets/ffmpeg.exe` | A static Windows build from [ffmpeg.org](https://ffmpeg.org/download.html) (e.g. gyan.dev full build) |
| `build_assets/deno.exe` | From [Deno releases](https://github.com/denoland/deno/releases/latest) — `deno-x86_64-pc-windows-msvc.zip` |
| `build_assets/app.ico` | Included in the repo (generated from `chrome-extension/icons/icon128.png`) |

PowerShell helper for Deno:

```powershell
Invoke-WebRequest "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" -OutFile build_assets/deno.zip
Expand-Archive build_assets/deno.zip build_assets/ -Force
Remove-Item build_assets/deno.zip
```

## 2. Build the one-file executable

```bash
python -m PyInstaller --noconfirm --onefile --windowed --name StreamStudio ^
  --icon build_assets\app.ico ^
  --add-data "templates;templates" --add-data "static;static" ^
  --add-binary "build_assets\ffmpeg.exe;." --add-binary "build_assets\deno.exe;." ^
  --collect-all yt_dlp --collect-all pystray --collect-all PIL ^
  --hidden-import _overlapped --hidden-import _asyncio --hidden-import asyncio ^
  app.py
```

Output: `dist/StreamStudio.exe` (self-contained).

## 3. Build the installer

```bash
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

Output: `Setup/StreamStudio-Setup.exe`.

## One-command rebuild

`update-and-rebuild.bat` updates dependencies (incl. yt-dlp), re-bundles FFmpeg, and runs steps 2–3.

## Notes

- The exe loads an updated `yt-dlp` from `%LOCALAPPDATA%\Stream Studio\pkgs` if present (the in-app self-updater), falling back to the frozen copy otherwise.
- `--windowed` removes the console; `--hidden-import _overlapped` is required so the bundled `asyncio` works on Windows.

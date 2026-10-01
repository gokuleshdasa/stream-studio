# Building & releasing Stream Studio

The repo ships **source only**. FFmpeg and Deno are not committed; `build.py`
fetches them. PyInstaller cannot cross-compile, so build on the OS you target
(CI does all three — see below). Background and rationale: [HANDOFF.md](HANDOFF.md).

## Quick start (any OS)

```bash
pip install -r requirements.txt
python build.py            # -> Setup/…
python build.py --check    # only verify version numbers are in sync
python build.py --no-package   # PyInstaller only
```

| OS | Extra prerequisite | Output |
|---|---|---|
| Windows 10/11 x64 | [Inno Setup 6](https://jrsoftware.org/isdl.php) | `Setup/StreamStudio-Setup.exe` |
| macOS (arm64 / x64) | – | `Setup/StreamStudio-macos-<arch>.tar.gz` |
| Linux x64 | – | `Setup/StreamStudio-linux-<arch>.tar.gz` |

Those output **file names are a contract** with the in-app updater
(`update_asset_name()` in `app.py`) — never rename them.

### What `build.py` does
1. Checks `APP_VERSION` (app.py) = `AppVersion` (installer.iss) and
   `EXTENSION_VERSION` (app.py) = `chrome-extension/manifest.json` version.
2. Ensures `build_assets/ffmpeg[.exe]` and `deno[.exe]`. If missing it copies
   them from the `imageio-ffmpeg` and `deno` PyPI wheels (static, per-OS).
   Put your own binaries there to override; delete them to re-pull latest.
3. Runs PyInstaller in **`--onedir`** mode (bundles `templates/`, `static/`,
   `chrome-extension/`, ffmpeg, deno, and `--collect-all` for yt_dlp, yt_dlp_ejs,
   curl_cffi, brotli, pystray, PIL). Output goes **outside** the repo/OneDrive
   (`C:\ss-build` on Windows, `$TMPDIR/ss-build` elsewhere; override with `SS_BUILD_DIR`) because sync clients lock
   files and break PyInstaller.
4. Packages: Inno Setup (Windows) or `tar.gz` with a `StreamStudio/` folder.

`update-and-rebuild.bat` (Windows) = upgrade pip deps (incl. yt-dlp) → delete
cached ffmpeg/deno → `python build.py`.

## Releasing

1. Add a section at the top of `CHANGELOG.md`: `## X.Y.Z — YYYY-MM-DD`.
2. Bump `APP_VERSION` (app.py) and `AppVersion` (installer.iss); if the
   extension changed also `EXTENSION_VERSION` (app.py) and manifest `version`.
3. `python build.py --check`, commit, push.
4. Tag → CI builds and publishes everything:
   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
   `.github/workflows/release.yml` builds Windows/macOS/Linux and attaches
   `StreamStudio-Setup.exe`, `StreamStudio-macos-arm64.tar.gz`,
   `StreamStudio-linux-x64.tar.gz`; release notes come from the CHANGELOG section.
5. Manual Windows-only alternative:
   `gh release create vX.Y.Z Setup/StreamStudio-Setup.exe --title "vX.Y.Z — summary" --notes-file notes.md`

Installed apps notice the release within 6 hours (or via the banner) and update
themselves once idle. `/releases/latest` skips drafts and pre-releases.

## Notes

- Never use `--onefile` (see HANDOFF §9: temp-extraction made pages go unstyled).
- At runtime the frozen app prefers a newer `yt_dlp`/`yt_dlp_ejs` from
  `DATA_DIR/pkgs` (the in-app self-updater) and falls back to the frozen copy.
- Windows uses `--windowed` (no console). macOS/Linux build plain executables.
- Unsigned binaries: Windows SmartScreen → *More info → Run anyway*;
  macOS → right-click → Open (or `xattr -dr com.apple.quarantine StreamStudio`).

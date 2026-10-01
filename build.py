#!/usr/bin/env python3
"""Cross-platform build for Stream Studio (Windows, macOS, Linux).

    python build.py               # build app + package for THIS OS
    python build.py --check       # only verify version numbers are in sync
    python build.py --no-package  # PyInstaller only, skip installer / tar.gz

What it does
  1. Verifies APP_VERSION (app.py) == AppVersion (installer.iss) and
     EXTENSION_VERSION (app.py) == chrome-extension/manifest.json "version".
  2. Makes sure ffmpeg + deno are in build_assets/ (uses what is already there,
     else pulls static builds from the `imageio-ffmpeg` and `deno` PyPI wheels,
     which ship per-OS binaries — so this works the same on all three OSes).
  3. Runs PyInstaller in --onedir mode (never --onefile: see CHANGELOG 1.6.4).
  4. Packages:
       Windows -> Setup/StreamStudio-Setup.exe        (Inno Setup)
       macOS   -> Setup/StreamStudio-macos-<arch>.tar.gz
       Linux   -> Setup/StreamStudio-linux-<arch>.tar.gz
     These file names are what the in-app updater looks for in a GitHub
     Release (see update_asset_name() in app.py) — do not rename them.

PyInstaller does not cross-compile: run this on each target OS (the GitHub
Actions workflow .github/workflows/release.yml does exactly that).
"""
import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
EXE = ".exe" if IS_WIN else ""
ASSETS = ROOT / "build_assets"
OUT_DIR = ROOT / "Setup"


def fail(msg):
    print(f"\nBUILD FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode != 0:
        fail(f"command exited with {r.returncode}")


def read(path):
    return (ROOT / path).read_text(encoding="utf-8-sig")


# --------------------------------------------------------------------------
def versions():
    app = read("app.py")
    iss = read("installer.iss")
    manifest = read("chrome-extension/manifest.json")
    g = lambda rx, text: (re.search(rx, text) or [None, None])[1]
    return {
        "APP_VERSION": g(r'^APP_VERSION\s*=\s*"([^"]+)"', app.replace("\r", "")) or g(r'APP_VERSION\s*=\s*"([^"]+)"', app),
        "installer.iss": g(r'#define AppVersion\s+"([^"]+)"', iss),
        "EXTENSION_VERSION": g(r'EXTENSION_VERSION\s*=\s*"([^"]+)"', app),
        "manifest.json": g(r'"version"\s*:\s*"([^"]+)"', manifest),
    }


def check_versions():
    v = versions()
    print("Versions:", v)
    if v["APP_VERSION"] != v["installer.iss"]:
        fail("APP_VERSION (app.py) != AppVersion (installer.iss)")
    if v["EXTENSION_VERSION"] != v["manifest.json"]:
        fail("EXTENSION_VERSION (app.py) != chrome-extension/manifest.json version")
    return v


# --------------------------------------------------------------------------
def ensure_binaries():
    ASSETS.mkdir(exist_ok=True)
    ff, dn = ASSETS / f"ffmpeg{EXE}", ASSETS / f"deno{EXE}"
    if not ff.exists():
        print("ffmpeg not in build_assets/ -> taking it from the imageio-ffmpeg wheel")
        run([sys.executable, "-m", "pip", "install", "--upgrade", "imageio-ffmpeg"])
        import imageio_ffmpeg
        shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), ff)
    if not dn.exists():
        print("deno not in build_assets/ -> taking it from the deno wheel")
        run([sys.executable, "-m", "pip", "install", "--upgrade", "deno"])
        import deno
        shutil.copy2(deno.find_deno_bin(), dn)
    for f in (ff, dn):
        if not IS_WIN:
            f.chmod(0o755)
    return ff, dn


def pyinstaller(dist, work):
    sep = ";" if IS_WIN else ":"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
           "--name", "StreamStudio", "--distpath", dist, "--workpath", work,
           "--add-data", f"templates{sep}templates",
           "--add-data", f"static{sep}static",
           "--add-data", f"chrome-extension{sep}chrome-extension",   # synced to the user data dir at runtime
           "--add-binary", f"build_assets{os.sep}ffmpeg{EXE}{sep}.",
           "--add-binary", f"build_assets{os.sep}deno{EXE}{sep}.",
           "--hidden-import", "_overlapped", "--hidden-import", "_asyncio", "--hidden-import", "asyncio"]
    for pkg in ("yt_dlp", "yt_dlp_ejs", "curl_cffi", "brotli", "pystray", "PIL"):
        cmd += ["--collect-all", pkg]
    if IS_WIN:
        # --windowed: no console. (On macOS it would produce a .app bundle with a
        # different layout than the updater expects, so mac/Linux stay plain.)
        cmd += ["--windowed", "--icon", str(ASSETS / "app.ico")]
    cmd.append("app.py")
    run(cmd, cwd=ROOT)


def package_windows(dist):
    iscc = None
    for cand in (os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
                 r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
                 r"C:\Program Files\Inno Setup 6\ISCC.exe"):
        if os.path.exists(cand):
            iscc = cand
            break
    iscc = iscc or shutil.which("ISCC")
    if not iscc:
        fail("Inno Setup 6 not found (https://jrsoftware.org/isdl.php)")
    run([iscc, f"/DDistDir={dist}", "installer.iss"], cwd=ROOT)
    return OUT_DIR / "StreamStudio-Setup.exe"


def package_unix(dist):
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    plat = "macos" if IS_MAC else "linux"
    OUT_DIR.mkdir(exist_ok=True)
    tarball = OUT_DIR / f"StreamStudio-{plat}-{arch}.tar.gz"
    folder = Path(dist) / "StreamStudio"
    (folder / "READ ME FIRST.txt").write_text(
        "Stream Studio\n=============\n"
        "Run ./StreamStudio  (opens http://127.0.0.1:5006, tray icon if your desktop has one).\n"
        "Start at login:     ./StreamStudio --enable-autostart\n"
        "Chrome extension:   ./StreamStudio --print-extension-path  -> chrome://extensions -> Developer mode -> Load unpacked\n"
        "The app keeps itself, yt-dlp and the extension up to date.\n", encoding="utf-8")
    with tarfile.open(tarball, "w:gz") as t:
        t.add(folder, arcname="StreamStudio")
    return tarball


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only verify version numbers")
    ap.add_argument("--no-package", action="store_true", help="stop after PyInstaller")
    args = ap.parse_args()

    v = check_versions()
    if args.check:
        return
    ensure_binaries()

    # Build OUTSIDE OneDrive/Dropbox: sync clients lock files inside
    # .dist-info\licenses and make PyInstaller fail randomly on Windows.
    # Not under %LOCALAPPDATA% either: Microsoft-Store Python virtualises
    # AppData writes, so ISCC would not find the PyInstaller output.
    # Override with SS_BUILD_DIR.
    base = Path(os.environ.get("SS_BUILD_DIR") or ("C:/ss-build" if IS_WIN else Path(os.environ.get("TMPDIR", "/tmp")) / "ss-build"))
    dist, work = base / "dist", base / "build"
    shutil.rmtree(dist, ignore_errors=True)
    pyinstaller(dist, work)
    if args.no_package:
        print(f"\nApp folder: {dist / 'StreamStudio'}")
        return
    artifact = package_windows(dist) if IS_WIN else package_unix(dist)
    print(f"\nDONE  v{v['APP_VERSION']}  ->  {artifact}  ({artifact.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()

==================================================================
  STREAM STUDIO  -  download | clip | convert | re-encode
  Windows installer edition
==================================================================

INSTALL
-------
  Run StreamStudio-Setup.exe and click Next > Next > Finish.
  (SmartScreen may warn because the installer is unsigned:
   "More info" > "Run anyway".)

  Everything is bundled - Python, yt-dlp, FFmpeg, Deno. Nothing else to
  install. The app opens http://127.0.0.1:5006 in your browser and saves
  finished files to  Downloads\Stream Studio.

IT RUNS QUIETLY IN THE BACKGROUND
---------------------------------
  No console window. A small icon sits in the system tray (bottom-right,
  click ^ if hidden). It starts at sign-in so the Chrome button always works.
    - Left-click the icon / "Open Stream Studio"  -> open the app
    - "Open Chrome extension folder"              -> where to load the extension
    - "Quit"                                      -> stop it
  To stop auto-start: delete "Stream Studio" from the Startup folder
  (Win+R, type  shell:common startup ).

IT UPDATES ITSELF (nothing to do)
---------------------------------
  - yt-dlp + yt-dlp-ejs (the engine that breaks whenever YouTube changes):
    checked at start and every 6 hours, swapped in silently, app restarts
    itself once no download is running.
  - Stream Studio itself: new GitHub releases are downloaded and installed
    silently (same idle rule). Turn either off in Settings (the gear icon).
  - Chrome extension: see below - it reloads itself.

CHROME EXTENSION (optional, recommended)
----------------------------------------
  Adds a Download button on videos, a right-click menu, and a download
  manager window. Load it ONCE:
    1. Chrome/Edge/Brave -> chrome://extensions  (edge://extensions)
    2. Turn on "Developer mode" (top-right)
    3. "Load unpacked" -> pick the folder shown by the tray item
       "Open Chrome extension folder"
       (= %LOCALAPPDATA%\Stream Studio\chrome-extension)
  The app keeps that folder current and the extension reloads itself
  when a newer version is available - you never repeat these steps.
  (If Chrome asks to "Disable developer mode extensions" on startup, choose
  Keep. That is a Chrome limitation for extensions loaded outside the Web Store.)

  Extension popup settings: app port (default 5006), hover-button mode,
  which media types to show.

TROUBLESHOOTING
---------------
  - Button does nothing: is the tray icon there? The app must be running.
  - Port in use: change it in the extension popup AND edit `port` in app.py.
  - Logs/settings: %LOCALAPPDATA%\Stream Studio\settings.json

Only download content you have the right to use.
Source, docs and handoff notes: https://github.com/gokuleshdasa/stream-studio

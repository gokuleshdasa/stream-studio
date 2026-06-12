==================================================================
  YT STUDIO EDITOR  —  download · convert · clip · re-encode
  (installer edition, v1.4.0 — background, auto-update, JS runtime)
==================================================================

WHAT'S IN THIS PACKAGE
----------------------
  StreamStudio-Setup.exe        The installer. Double-click and follow
                                  Next -> Next -> Finish. Installs the app,
                                  a Start Menu entry, a desktop shortcut, and
                                  an "Add/Remove Programs" uninstaller.
  chrome-extension\               The Chrome add-on (also installed by the
                                  setup into the app folder).
  ytstudio-chrome-extension.zip   The same extension, zipped for sharing.


----------------------------------
1) INSTALL THE APP
----------------------------------
  • Double-click  StreamStudio-Setup.exe
  • Windows SmartScreen may warn (the installer is unsigned):
    click "More info" -> "Run anyway", then approve the UAC prompt.
  • Click through the wizard. When it finishes you can launch it.
  • Start it any time from the Start Menu or the desktop shortcut
    "Stream Studio".

  The app opens your browser at  http://127.0.0.1:5001
  Finished files are saved to:   This PC > Downloads > "Stream Studio"

  To uninstall: Settings > Apps > "Stream Studio" > Uninstall.

  Everything (Python, ffmpeg, yt-dlp) is bundled inside the app — there
  is nothing else to install.


----------------------------------
   IT RUNS QUIETLY IN THE BACKGROUND
----------------------------------
  There is NO console/DOS window any more. The app runs as a small
  background service with an icon in the system tray (bottom-right of
  the taskbar, near the clock — you may need to click the ^ arrow).

  • It starts automatically every time you sign in to Windows, so the
    Chrome "Convert this video" button always works — nothing to start
    by hand.
  • Tray icon: left-click (or right-click > "Open Stream Studio") opens the
    app in your browser.
  • To stop it: right-click the tray icon > "Quit".
  • To turn off auto-start: delete the "Stream Studio" shortcut from
    the Startup folder (press Win+R, type  shell:common startup ).


----------------------------------
   STAYING UP TO DATE (automatic)
----------------------------------
  YouTube changes often, which can break the downloader engine (yt-dlp).
  The app handles this for you:

  • It quietly checks for a newer yt-dlp engine in the background.
  • When one exists, you get a Windows notification, and the tray menu
    shows "Update yt-dlp to <version>".
  • Click that menu item — it downloads the update and restarts itself.
    Nothing to reinstall.

  Chrome extension: if a future app version ships an improved extension,
  the extension's popup shows an "update available" notice with a button
  that opens chrome://extensions so you can reload it. (Unpacked Chrome
  extensions can't replace their own files automatically.)


----------------------------------
2) INSTALL THE CHROME EXTENSION (optional)
----------------------------------
  The extension puts a modern "Convert this video" card right above the
  YouTube player. Click it and the app opens with that video already
  loaded. The card auto-collapses to a small "Convert" pill if you don't
  act within a set time (default 20 seconds — change it in the extension
  popup). The app must be running for the card to do anything.

  To install:
    1. Chrome -> address bar -> chrome://extensions
    2. Turn ON "Developer mode" (top-right).
    3. Click "Load unpacked".
    4. Select the  chrome-extension  folder
       (either the one in this package, or the copy the installer placed
        in:  C:\Program Files\Stream Studio\chrome-extension ).
    5. Open any YouTube video — the card appears above the player.

  Extension settings (click the extension's toolbar icon):
    • App port (default 5001)
    • Auto-collapse delay in seconds (default 20)


----------------------------------
NOTES
----------------------------------
  • The on-video card and the toolbar popup both just hand the current
    YouTube URL to the local app; the app does the actual work.
  • Only use this for content you have the right to download.

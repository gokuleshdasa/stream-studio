// Stream Studio — injects a modern "Convert this video" card just above the
// YouTube player. Auto-collapses after a configurable delay (default 20s).
(function () {
  const DEFAULTS = { port: "5006", collapseDelay: 20 };
  let settings = { ...DEFAULTS };
  let collapseTimer = null;
  let lastHref = "";

  function loadSettings(cb) {
    try {
      chrome.storage.local.get(["port", "collapseDelay"], d => {
        settings.port = d.port || DEFAULTS.port;
        settings.collapseDelay = Number.isFinite(+d.collapseDelay) && +d.collapseDelay > 0
          ? +d.collapseDelay : DEFAULTS.collapseDelay;
        cb && cb();
      });
    } catch { cb && cb(); }
  }
  // react live to settings changes from the popup
  try {
    chrome.storage.onChanged.addListener(ch => {
      if (ch.port) settings.port = ch.port.newValue || DEFAULTS.port;
      if (ch.collapseDelay) settings.collapseDelay = +ch.collapseDelay.newValue || DEFAULTS.collapseDelay;
    });
  } catch {}

  function isWatch() { return /\/watch|\/shorts\//.test(location.pathname); }

  function findAnchor() {
    // the primary player element on a watch page; the card is inserted above it
    return document.querySelector("#player.ytd-watch-flexy")
        || document.querySelector("ytd-watch-flexy #player")
        || document.querySelector("#player")
        || document.querySelector("#movie_player");
  }

  function openApp() {
    const url = `http://127.0.0.1:${settings.port}/?u=${encodeURIComponent(location.href)}`;
    window.open(url, "_blank");
  }

  function clearTimer() { if (collapseTimer) { clearTimeout(collapseTimer); collapseTimer = null; } }
  function armCollapse(card) {
    clearTimer();
    collapseTimer = setTimeout(() => card.classList.add("yts-collapsed"), settings.collapseDelay * 1000);
  }

  function buildCard() {
    const card = document.createElement("div");
    card.id = "yts-card";
    card.innerHTML = `
      <div class="yts-glow"></div>
      <div class="yts-row">
        <span class="yts-badge">▶</span>
        <div class="yts-text">
          <div class="yts-title">Convert this video</div>
          <div class="yts-sub">Download · clip · re-encode in Stream Studio</div>
        </div>
        <button class="yts-cta" type="button">Open in Stream Studio →</button>
        <button class="yts-x" type="button" title="Collapse">▾</button>
      </div>
      <button class="yts-pill" type="button" title="Convert this video">
        <span class="yts-badge sm">▶</span><span>Convert</span>
      </button>`;

    card.querySelector(".yts-cta").addEventListener("click", openApp);
    card.querySelector(".yts-pill").addEventListener("click", e => {
      // collapsed pill: first click re-expands; from expanded it converts
      if (card.classList.contains("yts-collapsed")) {
        card.classList.remove("yts-collapsed");
        armCollapse(card);
      } else { openApp(); }
      e.stopPropagation();
    });
    card.querySelector(".yts-x").addEventListener("click", () => { clearTimer(); card.classList.add("yts-collapsed"); });

    // any interaction keeps it open
    ["mouseenter", "focusin"].forEach(ev => card.addEventListener(ev, clearTimer));
    card.addEventListener("mouseleave", () => { if (!card.classList.contains("yts-collapsed")) armCollapse(card); });
    return card;
  }

  function mount() {
    if (!isWatch()) { const ex = document.getElementById("yts-card"); if (ex) ex.remove(); return; }
    const anchor = findAnchor();
    if (!anchor || !anchor.parentNode) return;

    let card = document.getElementById("yts-card");
    if (!card) {
      card = buildCard();
      anchor.parentNode.insertBefore(card, anchor); // sits directly above the video
    } else if (card.nextSibling !== anchor) {
      anchor.parentNode.insertBefore(card, anchor); // keep it pinned above the player
    }

    // new video → re-expand and restart the timer
    if (location.href !== lastHref) {
      lastHref = location.href;
      card.classList.remove("yts-collapsed");
      requestAnimationFrame(() => card.classList.add("yts-in"));
      armCollapse(card);
    }
  }

  loadSettings(() => {
    mount();
    // YouTube is a SPA — keep the card present/pinned across navigations
    document.addEventListener("yt-navigate-finish", () => setTimeout(mount, 300));
    const obs = new MutationObserver(() => mount());
    obs.observe(document.documentElement, { childList: true, subtree: true });
  });
})();

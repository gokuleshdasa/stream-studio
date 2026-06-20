// Stream Studio — shows a one-click Download button on ANY page that the local
// Stream Studio app can grab media from. It asks the app (/api/supported) per
// URL; if a dedicated yt-dlp extractor handles the page, the button appears.
(function () {
  const DEFAULTS = { port: "5006", collapseDelay: 20 };
  let settings = { ...DEFAULTS };
  let lastChecked = "";
  let collapseTimer = null;

  function loadSettings(cb) {
    try {
      chrome.storage.local.get(["port", "collapseDelay"], d => {
        settings.port = d.port || DEFAULTS.port;
        const n = +d.collapseDelay;
        settings.collapseDelay = Number.isFinite(n) && n > 0 ? n : DEFAULTS.collapseDelay;
        cb && cb();
      });
    } catch { cb && cb(); }
  }
  try {
    chrome.storage.onChanged.addListener(ch => {
      if (ch.port) settings.port = ch.port.newValue || DEFAULTS.port;
      if (ch.collapseDelay) settings.collapseDelay = +ch.collapseDelay.newValue || DEFAULTS.collapseDelay;
    });
  } catch {}

  const base = () => `http://127.0.0.1:${settings.port}`;

  async function isSupported(u) {
    try {
      const r = await fetch(`${base()}/api/supported?u=${encodeURIComponent(u)}`, { cache: "no-store" });
      return (await r.json()).supported === true;
    } catch { return false; }   // app not running -> no button
  }

  function startDownload() {
    window.open(`${base()}/?u=${encodeURIComponent(location.href)}&dl=1`, "_blank");
  }

  function clearTimer() { if (collapseTimer) { clearTimeout(collapseTimer); collapseTimer = null; } }
  function armCollapse(card) {
    clearTimer();
    if (settings.collapseDelay > 0)
      collapseTimer = setTimeout(() => card.classList.add("yts-collapsed"), settings.collapseDelay * 1000);
  }

  function buildCard() {
    const card = document.createElement("div");
    card.id = "yts-card";
    card.innerHTML = `
      <div class="yts-glow"></div>
      <div class="yts-row">
        <span class="yts-badge">⬇</span>
        <div class="yts-text">
          <div class="yts-title">Download this media</div>
          <div class="yts-sub">One click · saved by Stream Studio</div>
        </div>
        <button class="yts-cta" type="button">Download →</button>
        <button class="yts-x" type="button" title="Collapse">▾</button>
      </div>
      <button class="yts-pill" type="button" title="Download this media">
        <span class="yts-badge sm">⬇</span><span>Download</span>
      </button>`;
    card.querySelector(".yts-cta").addEventListener("click", startDownload);
    card.querySelector(".yts-pill").addEventListener("click", e => {
      e.stopPropagation();
      if (card.classList.contains("yts-collapsed")) { card.classList.remove("yts-collapsed"); armCollapse(card); }
      else startDownload();
    });
    card.querySelector(".yts-x").addEventListener("click", () => { clearTimer(); card.classList.add("yts-collapsed"); });
    ["mouseenter", "focusin"].forEach(ev => card.addEventListener(ev, clearTimer));
    card.addEventListener("mouseleave", () => { if (!card.classList.contains("yts-collapsed")) armCollapse(card); });
    return card;
  }

  function showCard() {
    let card = document.getElementById("yts-card");
    if (!card) {
      card = buildCard();
      document.body.appendChild(card);
      requestAnimationFrame(() => card.classList.add("yts-in"));
      armCollapse(card);
    } else if (card.parentNode !== document.body) {
      document.body.appendChild(card);
    }
  }
  function hideCard() { const c = document.getElementById("yts-card"); if (c) c.remove(); }

  async function check() {
    const href = location.href;
    if (href === lastChecked) return;
    lastChecked = href;
    if (!/^https?:/i.test(href)) { hideCard(); return; }
    if (await isSupported(href)) showCard(); else hideCard();
  }

  loadSettings(() => {
    check();
    let last = location.href;
    setInterval(() => { if (location.href !== last) { last = location.href; check(); } }, 1200);
    document.addEventListener("yt-navigate-finish", () => setTimeout(check, 300));
  });
})();

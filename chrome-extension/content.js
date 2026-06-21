// Stream Studio content script — runs on every page (and frame).
//  • detects media (DOM <video>/<audio> + media links) and reports it
//  • shows a compact "Download" pill on yt-dlp-supported pages (top frame)
//  • Extended mode: an IDM-style hover Download button over each media element
(function () {
  if (window.__ss_loaded) return; window.__ss_loaded = true;
  const TOP = window.top === window;
  const DEFAULTS = { port: "5006", collapseDelay: 20, extended: false };
  let S = { ...DEFAULTS };
  const base = () => `http://127.0.0.1:${S.port}`;

  function load(cb) {
    try {
      chrome.storage.local.get(["port", "collapseDelay", "extended"], d => {
        S.port = d.port || DEFAULTS.port;
        const n = +d.collapseDelay; S.collapseDelay = Number.isFinite(n) && n > 0 ? n : DEFAULTS.collapseDelay;
        S.extended = !!d.extended; cb && cb();
      });
    } catch { cb && cb(); }
  }
  try {
    chrome.storage.onChanged.addListener(ch => {
      if (ch.port) S.port = ch.port.newValue || DEFAULTS.port;
      if (ch.extended) { S.extended = !!ch.extended.newValue; if (TOP) (S.extended ? enableHover() : disableHover()); }
    });
  } catch {}

  function send(type, extra) { return new Promise(res => { try { chrome.runtime.sendMessage({ type, ...extra }, res); } catch { res(); } }); }

  function toast(text) {
    if (!TOP) return;
    const t = document.createElement("div"); t.className = "ss-toast"; t.textContent = text;
    document.body.appendChild(t); requestAnimationFrame(() => t.classList.add("in"));
    setTimeout(() => { t.classList.remove("in"); setTimeout(() => t.remove(), 300); }, 3500);
  }

  function download(url, kind) {
    send("quickDownload", { url, referer: location.href, title: document.title, kind }).then(r => {
      if (r && r.via === "browser") toast("⬇ Downloading in your browser…");
      else if (r && r.job_id) toast("⬇ Downloading…  (saving to Downloads ▸ Stream Studio)");
      else toast((r && r.error) || "Couldn't start — is Stream Studio running?");
    });
  }

  // toasts requested by the background (right-click downloads, etc.)
  try { chrome.runtime.onMessage.addListener(m => { if (m && m.type === "toast") toast(m.text); }); } catch {}

  // ---- DOM media detection (runs in every frame) ----
  const MEDIA_LINK = /\.(mp4|m4v|webm|mkv|mov|mp3|m4a|aac|ogg|opus|flac|wav)(\?|#|$)/i;
  function domMedia() {
    const items = [];
    document.querySelectorAll("video, audio").forEach(el => {
      const src = el.currentSrc || el.src || "";
      if (/^https?:/i.test(src)) items.push({ url: src, ct: el.tagName === "AUDIO" ? "audio/" : "video/" });
      el.querySelectorAll("source").forEach(s => { if (/^https?:/i.test(s.src)) items.push({ url: s.src }); });
    });
    document.querySelectorAll("a[href]").forEach(a => { if (MEDIA_LINK.test(a.href)) items.push({ url: a.href }); });
    if (items.length) send("addDomMedia", { items });
  }

  // ---- compact "Download this page" pill (supported sites, top frame) ----
  async function supported(u) {
    try { const r = await fetch(`${base()}/api/supported?u=${encodeURIComponent(u)}`, { cache: "no-store" }); return (await r.json()).supported === true; }
    catch { return false; }
  }
  let lastHref = "";
  async function pillCheck() {
    if (!TOP) return;
    const href = location.href; if (href === lastHref) return; lastHref = href;
    const ex = document.getElementById("ss-pill");
    if (await supported(href)) { if (!ex) makePill(); } else if (ex) ex.remove();
  }
  function makePill() {
    const p = document.createElement("div"); p.id = "ss-pill";
    p.innerHTML = `<button class="ss-pill-btn" title="Download this page with Stream Studio"><span class="ss-ic">⬇</span><span>Download</span></button><button class="ss-pill-x" title="Hide">✕</button>`;
    p.querySelector(".ss-pill-btn").addEventListener("click", () => send("openApp", { url: location.href }));
    p.querySelector(".ss-pill-x").addEventListener("click", () => p.remove());
    document.body.appendChild(p); requestAnimationFrame(() => p.classList.add("in"));
  }

  // ---- IDM-style hover Download button over media (top frame) ----
  let hoverBtn = null, hoverEl = null, hideTimer = null;
  function ensureHoverBtn() {
    if (hoverBtn) return hoverBtn;
    hoverBtn = document.createElement("div"); hoverBtn.id = "ss-hover";
    hoverBtn.innerHTML = `<span class="ss-ic">⬇</span> Download`;
    hoverBtn.addEventListener("click", e => {
      e.stopPropagation(); e.preventDefault(); if (!hoverEl) return;
      const src = hoverEl.currentSrc || hoverEl.src || "";
      const kind = hoverEl.tagName === "AUDIO" ? "audio" : "video";
      if (/^https?:/i.test(src)) download(src, kind);
      else { send("openApp", { url: location.href }); toast("Opening Stream Studio for this player…"); }
    });
    hoverBtn.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    hoverBtn.addEventListener("mouseleave", scheduleHide);
    document.body.appendChild(hoverBtn);
    return hoverBtn;
  }
  function positionHover(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 120 || r.height < 60) { hideHover(); return; }   // skip tiny/icon players
    const b = ensureHoverBtn(); b.classList.add("show");
    b.style.top = (window.scrollY + r.top + 12) + "px";
    b.style.left = (window.scrollX + r.right - 12 - b.offsetWidth) + "px";
  }
  function scheduleHide() { hideTimer = setTimeout(hideHover, 400); }
  function hideHover() { if (hoverBtn) hoverBtn.classList.remove("show"); hoverEl = null; }
  function onOver(e) { const el = e.target.closest && e.target.closest("video, audio"); if (el) { hoverEl = el; clearTimeout(hideTimer); positionHover(el); } }
  function onOut(e) { if (e.target.closest && e.target.closest("video, audio")) scheduleHide(); }
  function onScroll() { if (hoverEl) positionHover(hoverEl); }
  function enableHover() { document.addEventListener("mouseover", onOver, true); document.addEventListener("mouseout", onOut, true); window.addEventListener("scroll", onScroll, true); }
  function disableHover() { document.removeEventListener("mouseover", onOver, true); document.removeEventListener("mouseout", onOut, true); window.removeEventListener("scroll", onScroll, true); hideHover(); }

  load(() => {
    domMedia();
    pillCheck();
    if (TOP && S.extended) enableHover();
    setInterval(domMedia, 3000);
    if (TOP) {
      let last = location.href;
      setInterval(() => { if (location.href !== last) { last = location.href; pillCheck(); } }, 1200);
      document.addEventListener("yt-navigate-finish", () => setTimeout(pillCheck, 300));
    }
  });
})();

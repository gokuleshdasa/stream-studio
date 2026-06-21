// Stream Studio content script:
//  • detects media (video/audio/images) on the page
//  • compact "Download" pill on yt-dlp-supported sites
//  • Extended mode: IDM-style hover Download button over media
//  • Right-click → a full download-manager window (filter, select, zip/separate)
(function () {
  if (window.__ss_loaded) return; window.__ss_loaded = true;
  const TOP = window.top === window;
  const DEFAULTS = { port: "5006", collapseDelay: 20, extended: false, types: { video: true, audio: true, image: true } };
  let S = { ...DEFAULTS };
  const base = () => `http://127.0.0.1:${S.port}`;

  function load(cb) {
    try {
      chrome.storage.local.get(["port", "collapseDelay", "extended", "types"], d => {
        S.port = d.port || DEFAULTS.port;
        const n = +d.collapseDelay; S.collapseDelay = Number.isFinite(n) && n > 0 ? n : DEFAULTS.collapseDelay;
        S.extended = !!d.extended;
        S.types = Object.assign({}, DEFAULTS.types, d.types || {});
        cb && cb();
      });
    } catch { cb && cb(); }
  }
  try {
    chrome.storage.onChanged.addListener(ch => {
      if (ch.port) S.port = ch.port.newValue || DEFAULTS.port;
      if (ch.types) S.types = Object.assign({}, DEFAULTS.types, ch.types.newValue || {});
      if (ch.extended) { S.extended = !!ch.extended.newValue; if (TOP) (S.extended ? enableHover() : disableHover()); }
    });
  } catch {}

  function send(type, extra) { return new Promise(res => { try { chrome.runtime.sendMessage({ type, ...extra }, res); } catch { res(); } }); }

  const IMG_EXT = /\.(jpg|jpeg|png|gif|webp|bmp|avif|svg)(\?|#|$)/i;
  const AUD_EXT = /\.(mp3|m4a|aac|ogg|opus|flac|wav)(\?|#|$)/i;
  const VID_EXT = /\.(mp4|m4v|webm|mkv|mov|m3u8|mpd)(\?|#|$)/i;
  function kindOf(url, ctHint) {
    if (ctHint) { if (/^image\//.test(ctHint)) return "image"; if (/^audio\//.test(ctHint)) return "audio"; if (/^video\//.test(ctHint)) return "video"; }
    if (IMG_EXT.test(url)) return "image";
    if (AUD_EXT.test(url)) return "audio";
    if (VID_EXT.test(url)) return "video";
    return "video";
  }

  function toast(text) {
    if (!TOP) return;
    const t = document.createElement("div"); t.className = "ss-toast"; t.textContent = text;
    document.body.appendChild(t); requestAnimationFrame(() => t.classList.add("in"));
    setTimeout(() => { t.classList.remove("in"); setTimeout(() => t.remove(), 300); }, 3500);
  }
  function download(url, kind) {
    send("quickDownload", { url, referer: location.href, title: document.title, kind }).then(r => {
      if (r && r.via === "browser") toast("⬇ Downloading in your browser…");
      else if (r && r.job_id) toast("⬇ Downloading…");
      else toast((r && r.error) || "Couldn't start — is Stream Studio running?");
    });
  }

  // ---- detection ----
  function scanDom() {
    const out = [];
    const push = (url, ct, name) => { if (/^https?:/i.test(url)) out.push({ url, kind: kindOf(url, ct), name: name || "" }); };
    document.querySelectorAll("video, audio").forEach(el => {
      const src = el.currentSrc || el.src || "";
      push(src, el.tagName === "AUDIO" ? "audio/" : "video/");
      el.querySelectorAll("source").forEach(s => push(s.src));
    });
    document.querySelectorAll("a[href]").forEach(a => { if (IMG_EXT.test(a.href) || AUD_EXT.test(a.href) || VID_EXT.test(a.href)) push(a.href); });
    document.querySelectorAll("img[src]").forEach(im => {
      if ((im.naturalWidth || im.width || 0) >= 200 && (im.naturalHeight || im.height || 0) >= 200) push(im.currentSrc || im.src, "image/");
    });
    return out;
  }
  function reportMedia() {
    const items = scanDom().filter(i => i.kind !== "image");   // video/audio to the badge/popup
    if (items.length) send("addDomMedia", { items });
  }

  // ---- supported-site pill ----
  async function supported(u) { try { const r = await fetch(`${base()}/api/supported?u=${encodeURIComponent(u)}`, { cache: "no-store" }); return (await r.json()).supported === true; } catch { return false; } }
  let lastHref = "";
  async function pillCheck() {
    if (!TOP) return;
    const href = location.href; if (href === lastHref) return; lastHref = href;
    const ex = document.getElementById("ss-pill");
    if (await supported(href)) { if (!ex) makePill(); } else if (ex) ex.remove();
  }
  function makePill() {
    const p = document.createElement("div"); p.id = "ss-pill";
    p.innerHTML = `<button class="ss-pill-btn"><span class="ss-ic">⬇</span><span>Download</span></button><button class="ss-pill-x" title="Hide">✕</button>`;
    p.querySelector(".ss-pill-btn").addEventListener("click", () => send("openApp", { url: location.href }));
    p.querySelector(".ss-pill-x").addEventListener("click", () => p.remove());
    document.body.appendChild(p); requestAnimationFrame(() => p.classList.add("in"));
  }

  // ---- hover button ----
  let hoverBtn = null, hoverEl = null, hideTimer = null;
  function ensureHoverBtn() {
    if (hoverBtn) return hoverBtn;
    hoverBtn = document.createElement("div"); hoverBtn.id = "ss-hover"; hoverBtn.innerHTML = `<span class="ss-ic">⬇</span> Download`;
    hoverBtn.addEventListener("click", e => {
      e.stopPropagation(); e.preventDefault(); if (!hoverEl) return;
      const src = hoverEl.currentSrc || hoverEl.src || "";
      const kind = hoverEl.tagName === "AUDIO" ? "audio" : "video";
      if (/^https?:/i.test(src)) download(src, kind); else { send("openApp", { url: location.href }); toast("Opening Stream Studio…"); }
    });
    hoverBtn.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    hoverBtn.addEventListener("mouseleave", scheduleHide);
    document.body.appendChild(hoverBtn);
    return hoverBtn;
  }
  function positionHover(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 120 || r.height < 60) { hideHover(); return; }
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

  // ---- download-manager modal ----
  function fileName(u) { try { const x = new URL(u); return decodeURIComponent(x.pathname.split("/").pop() || x.hostname); } catch { return u.slice(0, 50); } }
  async function openManager() {
    if (!TOP) return;
    if (document.getElementById("ss-modal-bg")) return;
    // gather: live DOM scan + sniffed-from-background, respecting type settings
    const sniff = (await send("getMedia", {}))?.media || [];
    const all = [...scanDom(), ...sniff.map(m => ({ url: m.url, kind: m.kind || kindOf(m.url, m.ct) }))];
    const seen = new Set(); let items = [];
    all.forEach(it => { if (it.url && !seen.has(it.url) && S.types[it.kind]) { seen.add(it.url); items.push({ ...it, name: fileName(it.url), checked: true }); } });

    const bg = document.createElement("div"); bg.id = "ss-modal-bg";
    bg.innerHTML = `
      <div id="ss-modal">
        <div class="ss-mhead">
          <div class="ss-mtitle">⬇ Stream Studio — Download manager</div>
          <button class="ss-mclose" title="Close">✕</button>
        </div>
        <div class="ss-mfilters"></div>
        <div class="ss-mtools">
          <label class="ss-selall"><input type="checkbox" class="ss-all" checked> Select all</label>
          <span class="ss-count"></span>
        </div>
        <ul class="ss-mlist"></ul>
        <div class="ss-mempty" style="display:none">No matching media found on this page.</div>
        <div class="ss-mfoot">
          <button class="ss-dl-sep">Download separately</button>
          <button class="ss-dl-zip">Zip &amp; download</button>
        </div>
      </div>`;
    document.body.appendChild(bg);
    requestAnimationFrame(() => bg.classList.add("in"));

    const $ = s => bg.querySelector(s);
    let filter = "all";
    const close = () => { bg.classList.remove("in"); setTimeout(() => bg.remove(), 200); };
    bg.addEventListener("click", e => { if (e.target === bg) close(); });
    $(".ss-mclose").addEventListener("click", close);

    function counts() { return { all: items.length, video: items.filter(i => i.kind === "video").length, audio: items.filter(i => i.kind === "audio").length, image: items.filter(i => i.kind === "image").length }; }
    function visible() { return items.filter(i => filter === "all" || i.kind === filter); }
    function renderFilters() {
      const c = counts();
      const chips = [["all", "All", c.all], ["video", "Video", c.video], ["audio", "Audio", c.audio], ["image", "Images", c.image]];
      $(".ss-mfilters").innerHTML = chips.filter(([k]) => k === "all" || c[k] > 0)
        .map(([k, label, n]) => `<button class="ss-chip${k === filter ? " on" : ""}" data-f="${k}">${label} <b>${n}</b></button>`).join("");
      $(".ss-mfilters").querySelectorAll(".ss-chip").forEach(b => b.addEventListener("click", () => { filter = b.dataset.f; renderFilters(); renderList(); }));
    }
    function renderList() {
      const list = $(".ss-mlist"); list.innerHTML = "";
      const vis = visible();
      $(".ss-mempty").style.display = vis.length ? "none" : "block";
      vis.forEach(it => {
        const li = document.createElement("li"); li.className = "ss-mi";
        const thumb = it.kind === "image" ? `<img class="ss-th" src="${it.url}">` : `<span class="ss-th ss-th-${it.kind}">${it.kind === "audio" ? "♪" : "▶"}</span>`;
        li.innerHTML = `<input type="checkbox" ${it.checked ? "checked" : ""}>
          <span class="ss-badge ss-${it.kind}">${it.kind === "image" ? "IMG" : it.kind === "audio" ? "AUD" : "VID"}</span>
          ${thumb}
          <span class="ss-name" title="${it.url.replace(/"/g, "&quot;")}">${it.name}</span>`;
        li.querySelector("input").addEventListener("change", e => { it.checked = e.target.checked; updateCount(); });
        list.appendChild(li);
      });
      updateCount();
    }
    function updateCount() {
      const sel = items.filter(i => i.checked).length;
      $(".ss-count").textContent = `${sel} selected`;
      const vis = visible(); const allOn = vis.length && vis.every(i => i.checked);
      $(".ss-all").checked = !!allOn;
    }
    $(".ss-all").addEventListener("change", e => { visible().forEach(i => i.checked = e.target.checked); renderList(); });
    $(".ss-dl-sep").addEventListener("click", () => {
      const sel = items.filter(i => i.checked); if (!sel.length) return;
      sel.forEach(i => download(i.url, i.kind));
      toast(`⬇ Downloading ${sel.length} item(s)…`); close();
    });
    $(".ss-dl-zip").addEventListener("click", () => {
      const sel = items.filter(i => i.checked); if (!sel.length) return;
      send("zipBundle", { items: sel.map(i => ({ url: i.url, title: i.name, kind: i.kind })), referer: location.href });
      toast("📦 Preparing your zip… it'll download when ready."); close();
    });

    renderFilters(); renderList();
  }

  // messages from background (toast / open manager)
  try {
    chrome.runtime.onMessage.addListener(m => {
      if (!m) return;
      if (m.type === "toast") toast(m.text);
      if (m.type === "openManager") openManager();
    });
  } catch {}

  load(() => {
    reportMedia(); pillCheck();
    if (TOP && S.extended) enableHover();
    setInterval(reportMedia, 3000);
    if (TOP) {
      let last = location.href;
      setInterval(() => { if (location.href !== last) { last = location.href; pillCheck(); } }, 1200);
      document.addEventListener("yt-navigate-finish", () => setTimeout(pillCheck, 300));
    }
  });
})();

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

  // ---- draggable + dismissible helpers -----------------------------------
  // Position and per-page "hide me" state persist across reloads via
  // chrome.storage.local — same store the popup uses.
  function loadKV(cb) {
    try { chrome.storage.local.get(["pillPos", "hoverPos", "hiddenPill", "hiddenHover"], cb); }
    catch { cb({}); }
  }
  function saveKV(patch) { try { chrome.storage.local.set(patch); } catch {} }

  // A cheap "which video am I on" key so Close is per-video, not per-domain.
  // For YouTube watch pages we use the ?v= id; for everything else, full URL.
  function currentVideoKey() {
    try {
      const u = new URL(location.href);
      if (/(^|\.)youtube\.com$/i.test(u.hostname) && u.pathname === "/watch") {
        return "yt:" + u.searchParams.get("v");
      }
      return u.origin + u.pathname + u.search;
    } catch { return location.href; }
  }

  function makeDraggable(el, handleEl, storageKey) {
    // Grab position from storage on install.
    loadKV(d => {
      const p = d && d[storageKey];
      if (p && Number.isFinite(p.left) && Number.isFinite(p.top)) applyPos(el, p);
    });

    let dragging = false, moved = false, startX = 0, startY = 0, baseL = 0, baseT = 0;
    handleEl.style.cursor = "grab";

    handleEl.addEventListener("pointerdown", ev => {
      // Ignore the actual click on child buttons — those still fire normally.
      if (ev.target !== handleEl && ev.target.closest("button") && ev.target !== handleEl) {
        // Only start drag on the pill background / hover-btn body, not on ✕ / Download button
        if (!ev.target.classList.contains("ss-drag-handle")) return;
      }
      dragging = true; moved = false;
      startX = ev.clientX; startY = ev.clientY;
      const r = el.getBoundingClientRect();
      baseL = r.left; baseT = r.top;
      handleEl.style.cursor = "grabbing";
      handleEl.setPointerCapture(ev.pointerId);
    });
    handleEl.addEventListener("pointermove", ev => {
      if (!dragging) return;
      const dx = ev.clientX - startX, dy = ev.clientY - startY;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 3) return;
      moved = true;
      const left = clamp(baseL + dx, 4, window.innerWidth - el.offsetWidth - 4);
      const top  = clamp(baseT + dy, 4, window.innerHeight - el.offsetHeight - 4);
      applyPos(el, { left, top });
    });
    handleEl.addEventListener("pointerup", ev => {
      if (!dragging) return;
      dragging = false;
      handleEl.style.cursor = "grab";
      try { handleEl.releasePointerCapture(ev.pointerId); } catch {}
      if (moved) {
        const r = el.getBoundingClientRect();
        saveKV({ [storageKey]: { left: r.left, top: r.top } });
      }
    });
    // Swallow the click that follows a drag so we don't accidentally trigger Download.
    handleEl.addEventListener("click", ev => { if (moved) { ev.stopPropagation(); ev.preventDefault(); moved = false; } }, true);
  }
  function clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, n)); }
  function applyPos(el, p) {
    el.style.left = p.left + "px";
    el.style.top  = p.top + "px";
    el.style.right = "auto";
    el.style.bottom = "auto";
  }
  function markHidden(kind, key) {
    loadKV(d => {
      const set = d[kind === "pill" ? "hiddenPill" : "hiddenHover"] || {};
      set[key] = Date.now();
      // Cap to last 500 videos so the object doesn't grow forever.
      const entries = Object.entries(set);
      if (entries.length > 500) {
        entries.sort((a, b) => a[1] - b[1]);
        const trimmed = Object.fromEntries(entries.slice(-500));
        saveKV(kind === "pill" ? { hiddenPill: trimmed } : { hiddenHover: trimmed });
      } else {
        saveKV(kind === "pill" ? { hiddenPill: set } : { hiddenHover: set });
      }
    });
  }
  function isHidden(kind, key, cb) {
    loadKV(d => {
      const set = d[kind === "pill" ? "hiddenPill" : "hiddenHover"] || {};
      cb(!!set[key]);
    });
  }

  // ---- supported-site pill ----
  // We only surface the corner pill on LISTING pages (channel / playlist /
  // search / user page) — a single-video page already has the on-video hover
  // button, so a second corner pill is just noise. The batch flag routes the
  // app to its Batch tab so a channel URL doesn't get treated as one video
  // and hang forever on /api/info.
  function isBatchUrl(url) {
    try {
      const u = new URL(url);
      const path = u.pathname;
      // YouTube: watch pages, youtu.be short links, and /shorts/ are single.
      // Everything else on YouTube (channel, @handle, /playlist, /c/, /user/)
      // is batch.
      if (/(^|\.)youtube\.com$/i.test(u.hostname)) {
        if (path === "/watch" && u.searchParams.get("v")) return false;
        if (/^\/shorts\//i.test(path)) return false;
        return true; // /playlist, /@handle, /channel/, /c/, /user/ etc.
      }
      if (u.hostname === "youtu.be") return false; // always a single video
      // Vimeo: /12345 is single, /channels/... is batch.
      if (/(^|\.)vimeo\.com$/i.test(u.hostname)) {
        if (/^\/\d+/.test(path)) return false;
        return /channels?|showcase|album|user/i.test(path);
      }
      // Direct media file URL is always single.
      if (/\.(mp4|m4v|webm|mkv|mov|mp3|m4a|aac|ogg|opus|flac|wav|m3u8|mpd)(\?|#|$)/i.test(path)) return false;
      // Generic heuristic: URL path names hint at listings.
      return /(playlist|channel|videos?\/?$|user\/|profile|category|tag\/|search)/i.test(path + u.search);
    } catch { return false; }
  }
  async function supported(u) { try { const r = await fetch(`${base()}/api/supported?u=${encodeURIComponent(u)}`, { cache: "no-store" }); return (await r.json()).supported === true; } catch { return false; } }
  let lastHref = "";
  async function pillCheck() {
    if (!TOP) return;
    const href = location.href; if (href === lastHref) return; lastHref = href;
    const ex = document.getElementById("ss-pill");
    // Skip pill on single-media pages — hover button already covers them.
    if (!isBatchUrl(href)) { if (ex) ex.remove(); return; }
    // Honour a persistent "hide for this page" the user set via ✕.
    isHidden("pill", currentVideoKey(), hidden => {
      if (hidden) { if (ex) ex.remove(); return; }
      if (ex) return; // already present
      supported(href).then(ok => { if (ok) makePill(); });
    });
  }
  function makePill() {
    const p = document.createElement("div"); p.id = "ss-pill";
    // The pill body ITSELF is a drag handle (marked ss-drag-handle). The
    // Download button and ✕ are children — they still click normally, only a
    // grab-and-move on empty pill space starts a drag.
    p.classList.add("ss-drag-handle");
    p.innerHTML = `<button class="ss-pill-btn"><span class="ss-ic">⬇</span><span>Fetch list</span></button><button class="ss-pill-x" title="Hide for this page">✕</button>`;
    p.querySelector(".ss-pill-btn").addEventListener("click", () => send("openApp", { url: location.href, batch: true }));
    p.querySelector(".ss-pill-x").addEventListener("click", ev => {
      ev.stopPropagation();
      markHidden("pill", currentVideoKey());
      p.remove();
    });
    document.body.appendChild(p); requestAnimationFrame(() => p.classList.add("in"));
    makeDraggable(p, p, "pillPos");
  }

  // ---- hover button ----
  // If the user has dragged it, we STOP auto-positioning relative to the
  // video and honour their placement (via chrome.storage.local -> hoverPos).
  // If the user has ✕'d it on this video, we don't show it at all.
  let hoverBtn = null, hoverEl = null, hideTimer = null;
  let userMovedHover = false;
  loadKV(d => { userMovedHover = !!(d && d.hoverPos); });
  function ensureHoverBtn() {
    if (hoverBtn) return hoverBtn;
    hoverBtn = document.createElement("div"); hoverBtn.id = "ss-hover";
    hoverBtn.classList.add("ss-drag-handle");
    hoverBtn.innerHTML =
      `<span class="ss-hover-body"><span class="ss-ic">⬇</span> Download</span>` +
      `<button class="ss-hover-x" title="Hide for this video">✕</button>`;
    hoverBtn.querySelector(".ss-hover-body").addEventListener("click", e => {
      e.stopPropagation(); e.preventDefault(); if (!hoverEl) return;
      const src = hoverEl.currentSrc || hoverEl.src || "";
      const kind = hoverEl.tagName === "AUDIO" ? "audio" : "video";
      if (/^https?:/i.test(src)) download(src, kind); else { send("openApp", { url: location.href }); toast("Opening Stream Studio…"); }
    });
    hoverBtn.querySelector(".ss-hover-x").addEventListener("click", ev => {
      ev.stopPropagation(); ev.preventDefault();
      markHidden("hover", currentVideoKey());
      hideHover();
    });
    hoverBtn.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    hoverBtn.addEventListener("mouseleave", scheduleHide);
    document.body.appendChild(hoverBtn);
    makeDraggable(hoverBtn, hoverBtn, "hoverPos");
    // Watch for a drag save so we flip auto-positioning off from now on.
    try {
      chrome.storage.onChanged.addListener(ch => { if (ch.hoverPos) userMovedHover = true; });
    } catch {}
    return hoverBtn;
  }
  function positionHover(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 120 || r.height < 60) { hideHover(); return; }
    isHidden("hover", currentVideoKey(), hidden => {
      if (hidden) { hideHover(); return; }
      const b = ensureHoverBtn(); b.classList.add("show");
      if (userMovedHover) return; // don't fight the user's chosen spot
      b.style.top = (window.scrollY + r.top + 12) + "px";
      b.style.left = (window.scrollX + r.right - 12 - b.offsetWidth) + "px";
    });
  }
  function scheduleHide() { hideTimer = setTimeout(hideHover, 400); }
  function hideHover() { if (hoverBtn) hoverBtn.classList.remove("show"); hoverEl = null; }
  function onOver(e) { const el = e.target.closest && e.target.closest("video, audio"); if (el) { hoverEl = el; clearTimeout(hideTimer); positionHover(el); } }
  function onOut(e) { if (e.target.closest && e.target.closest("video, audio")) scheduleHide(); }
  function onScroll() { if (hoverEl && !userMovedHover) positionHover(hoverEl); }
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

// Stream Studio — background service worker.
// Sniffs media network requests per tab, powers the right-click menu, and
// bridges downloads to the local Stream Studio app.

const AUDIO_EXT = /\.(mp3|m4a|aac|ogg|opus|flac|wav)(\?|#|$)/i;
const VIDEO_EXT = /\.(mp4|m4v|webm|mkv|mov|m3u8|mpd)(\?|#|$)/i;
const MEDIA_CT = /^(audio\/|video\/|application\/(x-mpegurl|vnd\.apple\.mpegurl|dash\+xml))/i;
const IGNORE = /\.(ts|m4s|jpg|jpeg|png|gif|webp|css|js|woff2?|svg)(\?|#|$)/i;

const tabMedia = {};   // tabId -> Map(url -> {url, kind, ct})
const refByUrl = {};   // url -> referer (best effort)

function kindOf(url, ct) {
  if (AUDIO_EXT.test(url) || /^audio\//i.test(ct || "")) return "audio";
  return "video";
}
function isMedia(url, ct) {
  if (IGNORE.test(url)) return false;
  return VIDEO_EXT.test(url) || AUDIO_EXT.test(url) || MEDIA_CT.test(ct || "");
}
function add(tabId, url, ct) {
  if (tabId < 0 || !/^https?:/i.test(url)) return;
  const m = tabMedia[tabId] || (tabMedia[tabId] = new Map());
  if (!m.has(url)) { m.set(url, { url, kind: kindOf(url, ct), ct: ct || "" }); badge(tabId); }
}
function badge(tabId) {
  const n = tabMedia[tabId] ? tabMedia[tabId].size : 0;
  try { chrome.action.setBadgeText({ tabId, text: n ? String(n) : "" }); } catch {}
  try { chrome.action.setBadgeBackgroundColor({ color: "#7c5cff" }); } catch {}
}

chrome.webRequest.onSendHeaders.addListener(d => {
  const ref = (d.requestHeaders || []).find(h => h.name.toLowerCase() === "referer");
  if (ref) refByUrl[d.url] = ref.value;
}, { urls: ["<all_urls>"] }, ["requestHeaders"]);

chrome.webRequest.onResponseStarted.addListener(d => {
  const ct = (d.responseHeaders || []).find(h => h.name.toLowerCase() === "content-type");
  if (isMedia(d.url, ct && ct.value)) add(d.tabId, d.url, ct && ct.value);
}, { urls: ["<all_urls>"], types: ["media", "xmlhttprequest", "object", "other"] }, ["responseHeaders"]);

chrome.tabs.onRemoved.addListener(id => { delete tabMedia[id]; });
chrome.tabs.onUpdated.addListener((id, info) => {
  if (info.status === "loading" && info.url) { tabMedia[id] = new Map(); badge(id); }
});

// ---- context menu ----
function setupMenu() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "ss_media", title: "⬇ Download this media (Stream Studio)",
      contexts: ["video", "audio"],
    });
    chrome.contextMenus.create({
      id: "ss_link", title: "⬇ Download link with Stream Studio",
      contexts: ["link"], targetUrlPatterns: ["*://*/*"],
    });
    chrome.contextMenus.create({
      id: "ss_page", title: "⬇ Download media on this page…",
      contexts: ["page", "frame", "selection", "image"],
    });
  });
}
chrome.runtime.onInstalled.addListener(setupMenu);
chrome.runtime.onStartup.addListener(setupMenu);

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const ref = tab && tab.url;
  if (info.menuItemId === "ss_media" && info.srcUrl) return go(info.srcUrl, ref, tab);
  if (info.menuItemId === "ss_link" && info.linkUrl) return go(info.linkUrl, ref, tab);
  // page: download everything detected on the tab; if nothing, open the app
  const items = (tab && tabMedia[tab.id]) ? [...tabMedia[tab.id].values()] : [];
  if (items.length) {
    items.forEach(m => go(m.url, ref, tab, m.kind));
    toastTab(tab && tab.id, `⬇ Downloading ${items.length} item${items.length === 1 ? "" : "s"}…`);
  } else {
    openApp((tab && tab.url) || "");
  }
});

function go(url, ref, tab, kind) {
  quickDownload(url, ref, tab && tab.title, kind).then(r => {
    const ok = r && (r.ok || r.job_id);
    toastTab(tab && tab.id, ok ? "⬇ Download started" : ((r && r.error) || "Download failed"));
  });
}
function toastTab(tabId, text) {
  if (tabId == null) return;
  try { chrome.tabs.sendMessage(tabId, { type: "toast", text }); } catch {}
}

// ---- messaging ----
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  const tabId = (msg && msg.tabId != null) ? msg.tabId : (sender.tab && sender.tab.id);
  if (msg.type === "getMedia") {
    reply({ media: tabMedia[tabId] ? [...tabMedia[tabId].values()] : [] });
    return true;
  }
  if (msg.type === "addDomMedia" && tabId != null) {
    (msg.items || []).forEach(it => { if (it.url) add(tabId, it.url, it.ct); });
    reply && reply({ ok: true });
    return true;
  }
  if (msg.type === "quickDownload") {
    quickDownload(msg.url, msg.referer || (sender.tab && sender.tab.url), msg.title, msg.kind)
      .then(r => reply && reply(r)).catch(e => reply && reply({ error: String(e) }));
    return true;
  }
  if (msg.type === "openApp") { openApp(msg.url); reply && reply({ ok: true }); return true; }
});

// ---- downloads ----
const DIRECT_FILE = /\.(mp4|m4v|webm|mkv|mov|mp3|m4a|aac|ogg|opus|flac|wav)(\?|#|$)/i;

function port(cb) {
  try { chrome.storage.local.get("port", d => cb(d.port || "5006")); }
  catch { cb("5006"); }
}
function openApp(u) {
  port(p => chrome.tabs.create({ url: `http://127.0.0.1:${p}/?u=${encodeURIComponent(u)}&dl=1` }));
}
function cookieHeader(url) {
  return new Promise(res => {
    try { chrome.cookies.getAll({ url }, cs => res((cs || []).map(c => `${c.name}=${c.value}`).join("; "))); }
    catch { res(""); }
  });
}
// Direct media files download through the BROWSER's own session, which already
// holds the page's cookies / Cloudflare clearance — so protected files work.
function browserDownload(url) {
  return new Promise(res => {
    try {
      chrome.downloads.download({ url, saveAs: false }, id => {
        const err = chrome.runtime.lastError;
        res(id ? { ok: true, via: "browser" } : { error: (err && err.message) || "download failed" });
      });
    } catch (e) { res({ error: String(e) }); }
  });
}
// Streaming (HLS/DASH) and page URLs go to the app; we pass the page cookies +
// the browser User-Agent so the app inherits the same authenticated session.
function appDownload(url, referer, title, kind) {
  return new Promise(resolve => {
    port(async p => {
      try {
        const headers = { "User-Agent": navigator.userAgent };
        if (referer) headers["Referer"] = referer;
        const ck = await cookieHeader(url); if (ck) headers["Cookie"] = ck;
        const r = await fetch(`http://127.0.0.1:${p}/api/quickdownload`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url, title: title || "media", kind: kind || kindOf(url, ""), headers }),
        });
        resolve(await r.json());
      } catch (e) { resolve({ error: "Stream Studio app isn't running" }); }
    });
  });
}
function quickDownload(url, referer, title, kind) {
  return DIRECT_FILE.test(url) ? browserDownload(url) : appDownload(url, referer, title, kind);
}

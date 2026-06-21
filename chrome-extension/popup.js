const $ = s => document.querySelector(s);
let tab = null;

function msg(m) { return new Promise(res => { try { chrome.runtime.sendMessage(m, res); } catch { res(); } }); }
function short(u) { try { const x = new URL(u); return (x.pathname.split("/").pop() || x.hostname) + (x.search ? "…" : ""); } catch { return u.slice(0, 60); } }
function kindOf(u) { return /\.(mp3|m4a|aac|ogg|opus|flac|wav)(\?|#|$)/i.test(u) ? "audio" : "video"; }

// ---- settings ----
chrome.storage.local.get(["port", "collapseDelay", "extended"], d => {
  if (d.port) $("#port").value = d.port;
  if (d.collapseDelay) $("#collapseDelay").value = d.collapseDelay;
  $("#extended").checked = !!d.extended;
});
$("#extended").addEventListener("change", () => chrome.storage.local.set({ extended: $("#extended").checked }));
$("#port").addEventListener("change", () => chrome.storage.local.set({ port: $("#port").value.trim() || "5006" }));
$("#collapseDelay").addEventListener("change", () => {
  let v = parseInt($("#collapseDelay").value, 10);
  if (!Number.isFinite(v) || v < 3) v = 20; if (v > 600) v = 600;
  $("#collapseDelay").value = v; chrome.storage.local.set({ collapseDelay: v });
});

// ---- current tab + media list ----
chrome.tabs.query({ active: true, currentWindow: true }, async tabs => {
  tab = tabs[0];
  if (!tab || !/^https?:/i.test(tab.url || "")) {
    $("#page").disabled = true;
    $("#list").innerHTML = '<div class="empty">Open a normal web page to use this.</div>';
    return;
  }
  const r = await msg({ type: "getMedia", tabId: tab.id });
  render((r && r.media) || []);
});

$("#page").addEventListener("click", () => { msg({ type: "openApp", url: tab.url }); window.close(); });

function render(media) {
  const list = $("#list");
  $("#count").textContent = media.length ? `(${media.length})` : "";
  if (!media.length) {
    list.innerHTML = '<div class="empty">Nothing detected yet. Play the video, or use the “Download this page” button above for sites like YouTube.</div>';
    return;
  }
  list.innerHTML = "";
  media.forEach(m => {
    const kind = m.kind || kindOf(m.url);
    const li = document.createElement("div"); li.className = "mi";
    li.innerHTML = `<span class="k">${kind === "audio" ? "AUD" : "VID"}</span>
      <span class="u" title="${m.url.replace(/"/g, "&quot;")}">${short(m.url)}</span>
      <button class="go">⬇</button>`;
    li.querySelector(".go").addEventListener("click", async () => {
      const res = await msg({ type: "quickDownload", url: m.url, referer: tab.url, title: tab.title, kind });
      $("#status").innerHTML = (res && res.job_id)
        ? '<span class="ok">Download started — saving to Downloads ▸ Stream Studio.</span>'
        : `<span class="bad">${(res && res.error) || "Couldn't start (is the app running?)"}</span>`;
    });
    list.appendChild(li);
  });
}

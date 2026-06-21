const $ = s => document.querySelector(s);
let tab = null;

function msg(m) { return new Promise(res => { try { chrome.runtime.sendMessage(m, res); } catch { res(); } }); }
function getPort() { return new Promise(r => { try { chrome.storage.local.get("port", d => r(d.port || "5006")); } catch { r("5006"); } }); }
async function pollJob(jobId) {
  const p = await getPort();
  for (let i = 0; i < 80; i++) {
    await new Promise(r => setTimeout(r, 1500));
    let j; try { j = await (await fetch(`http://127.0.0.1:${p}/api/progress/${jobId}`, { cache: "no-store" })).json(); } catch { continue; }
    if (j.status === "done") { $("#status").innerHTML = '<span class="ok">✓ Saved to Downloads ▸ Stream Studio.</span>'; return; }
    if (j.status === "error") { $("#status").innerHTML = `<span class="bad">✕ ${String(j.error || "failed").slice(0, 140)}</span>`; return; }
    $("#status").innerHTML = `<span>Downloading… ${Math.round(j.progress || 0)}%</span>`;
  }
}
function short(u) { try { const x = new URL(u); return (x.pathname.split("/").pop() || x.hostname) + (x.search ? "…" : ""); } catch { return u.slice(0, 60); } }
function kindOf(u) { return /\.(mp3|m4a|aac|ogg|opus|flac|wav)(\?|#|$)/i.test(u) ? "audio" : "video"; }

// ---- settings ----
chrome.storage.local.get(["port", "collapseDelay", "extended", "types"], d => {
  if (d.port) $("#port").value = d.port;
  if (d.collapseDelay) $("#collapseDelay").value = d.collapseDelay;
  $("#extended").checked = !!d.extended;
  const t = Object.assign({ video: true, audio: true, image: true }, d.types || {});
  $("#t_video").checked = t.video; $("#t_audio").checked = t.audio; $("#t_image").checked = t.image;
});
$("#extended").addEventListener("change", () => chrome.storage.local.set({ extended: $("#extended").checked }));
function saveTypes() { chrome.storage.local.set({ types: { video: $("#t_video").checked, audio: $("#t_audio").checked, image: $("#t_image").checked } }); }
["#t_video", "#t_audio", "#t_image"].forEach(s => $(s).addEventListener("change", saveTypes));
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
      if (res && res.via === "browser") $("#status").innerHTML = '<span class="ok">⬇ Downloading in your browser…</span>';
      else if (res && res.job_id) { $("#status").innerHTML = '<span>Starting…</span>'; pollJob(res.job_id); }
      else $("#status").innerHTML = `<span class="bad">${(res && res.error) || "Couldn't start (is the app running?)"}</span>`;
    });
    list.appendChild(li);
  });
}

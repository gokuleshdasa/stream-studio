const $ = s => document.querySelector(s);
let currentUrl = null;

function isSupported(u) {
  // Any normal web page is fair game — the app (yt-dlp) decides if it's grabbable.
  return /^https?:\/\//i.test(u || "") && !/^https?:\/\/(chrome|edge|about)/i.test(u || "");
}

// load saved settings
chrome.storage.local.get(["port", "collapseDelay"], d => {
  if (d.port) $("#port").value = d.port;
  if (d.collapseDelay) $("#collapseDelay").value = d.collapseDelay;
});
$("#port").addEventListener("change", () => chrome.storage.local.set({ port: $("#port").value.trim() || "5006" }));
$("#collapseDelay").addEventListener("change", () => {
  let v = parseInt($("#collapseDelay").value, 10);
  if (!Number.isFinite(v) || v < 3) v = 20;
  if (v > 600) v = 600;
  $("#collapseDelay").value = v;
  chrome.storage.local.set({ collapseDelay: v });
});

chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
  const tab = tabs[0];
  currentUrl = tab?.url || "";
  if (isSupported(currentUrl)) {
    $("#vid").textContent = (tab.title || currentUrl).replace(/ - YouTube$/, "");
    $("#send").disabled = false;
  } else {
    $("#vid").innerHTML = '<span class="bad">Open a media page first (this isn\'t a web page).</span>';
    $("#send").disabled = true;
  }
});

$("#send").addEventListener("click", () => {
  if (!isSupported(currentUrl)) return;
  const port = ($("#port").value.trim() || "5006");
  const appUrl = `http://127.0.0.1:${port}/?u=${encodeURIComponent(currentUrl)}`;
  chrome.tabs.create({ url: appUrl });
  window.close();
});

$("#copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(currentUrl || "");
    $("#status").innerHTML = '<span class="ok">URL copied.</span>';
  } catch { $("#status").innerHTML = '<span class="bad">Copy failed.</span>'; }
});

// ---- check whether the app ships a newer extension than the one loaded ----
function cmpVer(a, b) {
  const pa = String(a).split("."), pb = String(b).split(".");
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (parseInt(pa[i] || 0, 10)) - (parseInt(pb[i] || 0, 10));
    if (d) return d;
  }
  return 0;
}
(async function checkExtensionUpdate() {
  const port = ($("#port").value.trim() || "5006");
  const mine = chrome.runtime.getManifest().version;
  try {
    const r = await fetch(`http://127.0.0.1:${port}/api/version`, { cache: "no-store" });
    const d = await r.json();
    if (d.extension_version && cmpVer(d.extension_version, mine) > 0) {
      $("#updtext").textContent =
        `You have v${mine}; the app now includes v${d.extension_version}. Reload the unpacked extension to update.`;
      $("#updnotice").style.display = "block";
    }
  } catch { /* app not running — nothing to check */ }
})();

$("#updbtn").addEventListener("click", () => {
  chrome.tabs.create({ url: "chrome://extensions" });
  window.close();
});

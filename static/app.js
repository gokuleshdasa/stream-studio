"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const PALETTE = ["#7c5cff", "#19d3da", "#ff5ca8", "#37e29a", "#ffb020", "#ff6b6b", "#5c9bff", "#c46cff"];

const state = {
  info: null,
  duration: 0,
  mode: "audio",
  merge: true,
  audioFormat: "mp3",
  audioBitrate: "192",
  videoFormat: "mp4",
  videoBitrate: "original",
  videoQuality: "best",
  regions: [],          // {id,name,start,end,color}
  selectedId: null,
  seq: 0,
  poll: null,
};

let player = null, ytReady = false, playerReady = false;
let media = null;        // unified adapter over YouTube iframe OR HTML5 media
let previewEnd = null;   // when set, auto-pause at this time
let previewTimer = null; // downgrade UI if a preview stream never loads

/* unified media adapter so the timeline works for any player */
function ytAdapter() {
  return {
    currentTime: () => { try { return player.getCurrentTime() || 0; } catch { return 0; } },
    seek: (t) => { try { player.seekTo(t, true); } catch {} },
    play: () => { try { player.playVideo(); } catch {} },
    pause: () => { try { player.pauseVideo(); } catch {} },
    isPlaying: () => { try { return player.getPlayerState() === 1; } catch { return false; } },
  };
}
function htmlAdapter(el) {
  return {
    currentTime: () => el.currentTime || 0,
    seek: (t) => { try { el.currentTime = t; } catch {} },
    play: () => { el.play().catch(() => {}); },
    pause: () => el.pause(),
    isPlaying: () => !el.paused,
  };
}
window.onYouTubeIframeAPIReady = () => { ytReady = true; };

/* ---------- helpers ---------- */
function fmtTime(s) {
  s = Math.max(0, s || 0);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
           : `${m}:${String(sec).padStart(2, "0")}`;
}
function parseTime(str) {
  if (str == null) return 0;
  str = String(str).trim();
  if (/^\d+(\.\d+)?$/.test(str)) return parseFloat(str);
  const p = str.split(":").map(Number);
  if (p.some(isNaN)) return 0;
  return p.reduce((a, v) => a * 60 + v, 0);
}
function fmtSize(b) {
  if (b < 1024) return b + " B";
  if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
  if (b < 1073741824) return (b / 1048576).toFixed(1) + " MB";
  return (b / 1073741824).toFixed(2) + " GB";
}
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function escapeHtml(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function flash(el){el.style.borderColor="var(--err)";setTimeout(()=>el.style.borderColor="",600);}
async function api(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || "Request failed");
  return j;
}
function toggleSpin(sel, on) {
  const b = $(sel);
  b.querySelector(".spinner").hidden = !on;
  b.querySelector(".btn-label").style.opacity = on ? .5 : 1;
  b.disabled = on;
}

/* ---------- load url ---------- */
$("#loadBtn").addEventListener("click", loadUrl);
$("#url").addEventListener("keydown", e => { if (e.key === "Enter") loadUrl(); });

async function loadUrl() {
  const url = $("#url").value.trim();
  const err = $("#loadErr"); err.hidden = true;
  if (!url) { err.textContent = "Please paste a URL first."; err.hidden = false; return; }
  toggleSpin("#loadBtn", true);
  try {
    const info = await api("/api/info", { url });
    state.info = info; state.duration = info.duration || 0;
    renderStudio(info);
  } catch (e) { err.textContent = e.message; err.hidden = false; }
  finally { toggleSpin("#loadBtn", false); }
}

/* ---------- render studio ---------- */
function renderStudio(info) {
  $("#studio").hidden = false;
  $("#mTitle").textContent = info.title || "Untitled";
  $("#mSub").textContent = [info.extractor, info.uploader, fmtTime(info.duration)].filter(Boolean).join(" · ");
  $("#durTime").textContent = fmtTime(info.duration);

  const vq = $("#videoQ");
  vq.innerHTML = '<button class="active" data-v="best">Best</button>';
  (info.video_qualities || []).forEach(q => {
    const b = document.createElement("button");
    b.dataset.v = q.height;
    b.textContent = q.height + "p" + (q.fps && q.fps > 31 ? q.fps : "");
    vq.appendChild(b);
  });
  bindPills(vq, "videoQuality");

  $("#srcAbr").textContent = info.source_audio_bitrates?.length ? `(source ≈ ${info.source_audio_bitrates[0]}k)` : "";

  playerReady = false;
  player = null;
  media = null;
  clearTimeout(previewTimer);
  resetClipUI();
  const stage = $("#player");
  stage.innerHTML = "";
  const thumb = info.thumbnail
    ? `<img src="${info.thumbnail}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover">` : "";

  if (!info.duration) {
    // No duration -> can't build a timeline -> download-only experience
    stage.innerHTML = thumb;
    setClipMode("downloadOnly");
  } else if (info.is_youtube && info.id && ytReady) {
    // YouTube: native iframe player (full experience)
    player = new YT.Player("player", {
      videoId: info.id,
      playerVars: { rel: 0, modestbranding: 1, controls: 1 },
      events: {
        onReady: () => { playerReady = true; },
        onStateChange: e => {
          $("#playBtn").textContent = (e.data === YT.PlayerState.PLAYING) ? "⏸" : "▶";
        },
      },
    });
    media = ytAdapter();
  } else if (info.preview_url) {
    // Any other site: HTML5 <video>/<audio> via our streaming proxy.
    // Optimistically full; we downgrade the UI if the stream won't load.
    if (info.media_kind === "audio") {
      const poster = info.thumbnail
        ? `<img src="${info.thumbnail}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.5">` : "";
      stage.innerHTML = poster +
        `<audio id="h5" src="${info.preview_url}" preload="metadata" controls
          style="position:absolute;left:12px;right:12px;bottom:12px;width:calc(100% - 24px)"></audio>`;
    } else {
      stage.innerHTML =
        `<video id="h5" src="${info.preview_url}" preload="metadata" controls playsinline
          ${info.thumbnail ? `poster="${info.thumbnail}"` : ""}
          style="position:absolute;inset:0;width:100%;height:100%;background:#000"></video>`;
    }
    const el = $("#h5");
    media = htmlAdapter(el);
    el.addEventListener("loadedmetadata", () => {
      playerReady = true; clearTimeout(previewTimer); setClipMode("full");
    });
    el.addEventListener("play", () => $("#playBtn").textContent = "⏸");
    el.addEventListener("pause", () => $("#playBtn").textContent = "▶");
    const downgrade = () => {
      clearTimeout(previewTimer);
      if (playerReady) return;
      media = null; stage.innerHTML = thumb; setClipMode("noPreview");
    };
    el.addEventListener("error", downgrade);
    previewTimer = setTimeout(downgrade, 7000);   // never loaded -> degrade
  } else {
    // No previewable stream at all: thumbnail + timestamp-only clipping
    stage.innerHTML = thumb;
    setClipMode("noPreview");
  }

  state.regions = []; state.selectedId = null; state.seq = 0;
  buildRuler();
  renderTrack();
  renderRegionList();
  hideEditor();
  $("#result").hidden = true;
  $("#studio").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- adaptive UI: degrade gracefully when preview/clip won't work ---------- */
function resetClipUI() {
  const tr = $(".transport"), tl = $(".timeline-block"), pr = $("#previewRegion");
  if (tr) tr.style.display = "";
  if (tl) tl.style.display = "";
  if (pr) pr.style.display = "";
  removePlayerNote();
}
function removePlayerNote() { const n = $("#playerNote"); if (n) n.remove(); }
function addPlayerNote(title, msg) {
  removePlayerNote();
  const note = document.createElement("div");
  note.id = "playerNote";
  note.className = "player-note";
  note.innerHTML = `<span class="pn-badge">${escapeHtml(title)}</span><div>${escapeHtml(msg)}</div>`;
  $("#player").appendChild(note);
}
function setClipMode(mode) {
  if (mode === "full") { resetClipUI(); return; }
  if (mode === "noPreview") {
    const tr = $(".transport"), pr = $("#previewRegion");
    if (tr) tr.style.display = "none";       // no player -> hide play/scrub transport
    if (pr) pr.style.display = "none";       // "preview region" can't play
    addPlayerNote("Preview not available", "You can still set clip times by typing them below.");
    toast("Live preview isn’t available for this source",
          "Clipping by exact start/end times still works — or just hit Convert & Download for the whole file.");
  } else if (mode === "downloadOnly") {
    const tr = $(".transport"), tl = $(".timeline-block");
    if (tr) tr.style.display = "none";
    if (tl) tl.style.display = "none";       // no timeline at all
    hideEditor();
    addPlayerNote("Clipping unavailable here", "Use “Convert & Download” to grab the full file.");
    toast("This source can’t be clipped here",
          "No timeline is available for it — use Convert & Download to get the full file.");
  }
}

/* gentle, non-blocking toast (auto-dismisses, never modal) */
function toast(title, msg, ms = 9000) {
  let wrap = $("#toastWrap");
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.id = "toastWrap"; wrap.className = "toast-wrap";
    document.body.appendChild(wrap);
  }
  const t = document.createElement("div");
  t.className = "toast";
  t.innerHTML = `<div class="ti">ℹ</div>
    <div class="tx"><b>${escapeHtml(title)}</b>${escapeHtml(msg)}</div>
    <button class="tc" aria-label="dismiss">✕</button>`;
  const close = () => { t.classList.add("out"); setTimeout(() => t.remove(), 300); };
  t.querySelector(".tc").addEventListener("click", close);
  wrap.appendChild(t);
  if (ms) setTimeout(close, ms);
}

/* ---------- ruler ---------- */
function buildRuler() {
  const ruler = $("#ruler");
  ruler.innerHTML = "";
  const dur = state.duration; if (!dur) return;
  const targetTicks = 8;
  const niceSteps = [1,2,5,10,15,30,60,120,300,600,900,1800,3600];
  let step = niceSteps.find(s => dur / s <= targetTicks) || 3600;
  for (let t = 0; t <= dur; t += step) {
    const tick = document.createElement("div");
    tick.className = "tick";
    tick.style.left = (t / dur * 100) + "%";
    tick.innerHTML = `<span>${fmtTime(t)}</span>`;
    ruler.appendChild(tick);
  }
}

/* ---------- track render ---------- */
const lane = $("#trackLane");
function pctLeft(t) { return state.duration ? (t / state.duration * 100) : 0; }

function renderTrack() {
  // remove existing blocks (keep ghost + playhead)
  $$(".region-blk", lane).forEach(e => e.remove());
  const sorted = [...state.regions];
  sorted.forEach(r => {
    const el = document.createElement("div");
    el.className = "region-blk" + (r.id === state.selectedId ? " sel" : "");
    el.style.left = pctLeft(r.start) + "%";
    el.style.width = Math.max(0.6, pctLeft(r.end - r.start)) + "%";
    el.style.background = `linear-gradient(135deg, ${r.color}, ${r.color}bb)`;
    el.dataset.id = r.id;
    el.innerHTML = `<div class="handle l"></div>
      <div class="blk-name">${escapeHtml(r.name)}</div>
      <div class="blk-dur">${fmtTime(r.end - r.start)}</div>
      <div class="handle r"></div>`;
    lane.appendChild(el);
  });
}

/* ---------- pointer interactions on the lane ---------- */
let drag = null;  // {type, id, startX, origStart, origEnd, laneRect}

function timeAtClientX(clientX, rect) {
  return clamp((clientX - rect.left) / rect.width * state.duration, 0, state.duration);
}

lane.addEventListener("pointerdown", e => {
  if (!state.duration) return;
  const rect = lane.getBoundingClientRect();
  const blk = e.target.closest(".region-blk");
  lane.setPointerCapture(e.pointerId);

  if (blk) {
    const id = blk.dataset.id;
    selectRegion(id);
    const r = state.regions.find(x => x.id === id);
    if (e.target.classList.contains("handle")) {
      drag = { type: e.target.classList.contains("l") ? "trim-l" : "trim-r", id, rect, origStart: r.start, origEnd: r.end };
    } else {
      drag = { type: "move", id, rect, startT: timeAtClientX(e.clientX, rect), origStart: r.start, origEnd: r.end };
    }
  } else {
    // create new region by dragging
    const t = timeAtClientX(e.clientX, rect);
    drag = { type: "create", rect, anchor: t };
    const g = $("#ghostRegion");
    g.hidden = false; g.style.left = pctLeft(t) + "%"; g.style.width = "0%";
  }
  e.preventDefault();
});

lane.addEventListener("pointermove", e => {
  if (!drag) return;
  const t = timeAtClientX(e.clientX, drag.rect);

  if (drag.type === "create") {
    const a = Math.min(drag.anchor, t), b = Math.max(drag.anchor, t);
    const g = $("#ghostRegion");
    g.style.left = pctLeft(a) + "%"; g.style.width = pctLeft(b - a) + "%";
    drag.cur = { a, b };
  } else {
    const r = state.regions.find(x => x.id === drag.id); if (!r) return;
    if (drag.type === "move") {
      const len = drag.origEnd - drag.origStart;
      let ns = clamp(drag.origStart + (t - drag.startT), 0, state.duration - len);
      r.start = ns; r.end = ns + len;
    } else if (drag.type === "trim-l") {
      r.start = clamp(t, 0, r.end - 0.2);
    } else if (drag.type === "trim-r") {
      r.end = clamp(t, r.start + 0.2, state.duration);
    }
    renderTrack();
    if (state.selectedId === drag.id) fillEditor(r);
  }
});

lane.addEventListener("pointerup", e => {
  if (!drag) return;
  if (drag.type === "create") {
    $("#ghostRegion").hidden = true;
    const c = drag.cur;
    if (c && (c.b - c.a) >= 0.3) addRegion(c.a, c.b);
  }
  drag = null;
});

/* ---------- regions CRUD ---------- */
function addRegion(start, end, name) {
  state.seq += 1;
  const r = {
    id: "r" + state.seq + "_" + Date.now().toString(36),
    name: name || `Part ${state.regions.length + 1}`,
    start, end,
    color: PALETTE[state.regions.length % PALETTE.length],
  };
  state.regions.push(r);
  selectRegion(r.id);
  renderTrack(); renderRegionList();
  return r;
}
function deleteRegion(id) {
  state.regions = state.regions.filter(r => r.id !== id);
  if (state.selectedId === id) { state.selectedId = null; hideEditor(); }
  renderTrack(); renderRegionList();
}
function selectRegion(id) {
  state.selectedId = id;
  const r = state.regions.find(x => x.id === id);
  renderTrack(); renderRegionList();
  if (r) { fillEditor(r); $("#regionEditor").hidden = false; }
}
function hideEditor() { $("#regionEditor").hidden = true; }

function fillEditor(r) {
  $("#reSwatch").style.background = r.color;
  if (document.activeElement !== $("#regName")) $("#regName").value = r.name;
  if (document.activeElement !== $("#tsStart")) $("#tsStart").value = fmtTime(r.start);
  if (document.activeElement !== $("#tsEnd")) $("#tsEnd").value = fmtTime(r.end);
}

$("#regName").addEventListener("input", () => {
  const r = cur(); if (!r) return;
  r.name = $("#regName").value || r.name;
  renderTrack(); renderRegionList();
});
$("#tsStart").addEventListener("change", () => {
  const r = cur(); if (!r) return;
  r.start = clamp(parseTime($("#tsStart").value), 0, r.end - 0.2);
  renderTrack(); fillEditor(r); renderRegionList();
});
$("#tsEnd").addEventListener("change", () => {
  const r = cur(); if (!r) return;
  r.end = clamp(parseTime($("#tsEnd").value), r.start + 0.2, state.duration);
  renderTrack(); fillEditor(r); renderRegionList();
});
$("#delRegion").addEventListener("click", () => { if (state.selectedId) deleteRegion(state.selectedId); });
$("#previewRegion").addEventListener("click", () => { const r = cur(); if (r) previewRange(r.start, r.end); });
function cur() { return state.regions.find(x => x.id === state.selectedId); }

function renderRegionList() {
  const ul = $("#regionList"); ul.innerHTML = "";
  $("#tlHint").style.display = state.regions.length ? "none" : "block";
  [...state.regions].sort((a, b) => a.start - b.start).forEach(r => {
    const li = document.createElement("li");
    if (r.id === state.selectedId) li.classList.add("sel");
    li.innerHTML = `<span class="rg-dot" style="background:${r.color}"></span>
      <span class="rg-name">${escapeHtml(r.name)}</span>
      <span class="rg-time">${fmtTime(r.start)} → ${fmtTime(r.end)}</span>
      <button class="rg-del" title="remove">✕</button>`;
    li.addEventListener("click", e => { if (!e.target.classList.contains("rg-del")) selectRegion(r.id); });
    li.querySelector(".rg-del").addEventListener("click", e => { e.stopPropagation(); deleteRegion(r.id); });
    ul.appendChild(li);
  });
}

/* ---------- transport + playhead ---------- */
$("#markBtn").addEventListener("click", () => {
  const t = curTime();
  const end = Math.min(state.duration, t + Math.min(10, state.duration * 0.1 || 10));
  addRegion(t, end);
});
$("#playBtn").addEventListener("click", () => {
  if (!media) return;
  if (media.isPlaying()) media.pause(); else { previewEnd = null; media.play(); }
});
$("#stopBtn").addEventListener("click", () => { if (media) { previewEnd = null; media.pause(); media.seek(0); } });

function previewRange(s, e) {
  if (!media || !playerReady) return;
  previewEnd = e;
  media.seek(s);
  media.play();
}
function curTime() {
  return media && playerReady ? media.currentTime() : 0;
}
function tick() {
  if (state.duration && media && playerReady) {
    const t = curTime();
    $("#playhead").style.left = pctLeft(t) + "%";
    $("#curTime").textContent = fmtTime(t);
    if (previewEnd != null && t >= previewEnd) { media.pause(); previewEnd = null; }
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

// click ruler to seek
$("#ruler").addEventListener("click", e => {
  if (!media || !playerReady) return;
  const rect = e.currentTarget.getBoundingClientRect();
  media.seek(timeAtClientX(e.clientX, rect));
});

/* ---------- segmented mode + merge ---------- */
function bindSeg(segSel, key, attr, onChange) {
  const seg = $(segSel); const btns = $$("button", seg); const glide = $(".seg-glide", seg);
  const move = i => glide.style.transform = `translateX(${i * 100}%)`;
  btns.forEach((b, i) => b.addEventListener("click", () => {
    btns.forEach(x => x.classList.remove("active")); b.classList.add("active"); move(i);
    state[key] = b.dataset[attr]; onChange && onChange(b.dataset[attr]);
  }));
  move(btns.findIndex(b => b.classList.contains("active")));
}
bindSeg("#modeSeg", "mode", "mode", updateGroups);
bindSeg("#mergeSeg", "merge", "merge", v => state.merge = v === "1");
function updateGroups() {
  const m = state.mode;
  state.merge = m === "both" ? state.merge : true;
  $$(".opt-group[data-show]").forEach(g => g.hidden = !g.dataset.show.split(" ").includes(m));
}
updateGroups();

/* ---------- pill groups ---------- */
function bindPills(container, key) {
  $$("button", container).forEach(b => b.addEventListener("click", () => {
    $$("button", container).forEach(x => x.classList.remove("active"));
    b.classList.add("active"); state[key] = b.dataset.v;
    if (key === "audioFormat") toggleBitrate(b.dataset.v);
  }));
}
bindPills($("#audioFmt"), "audioFormat");
bindPills($("#audioBr"), "audioBitrate");
bindPills($("#videoFmt"), "videoFormat");
bindPills($("#videoBr"), "videoBitrate");
function toggleBitrate(fmt) {
  const lossless = fmt === "wav" || fmt === "flac";
  $("#abrField").style.opacity = lossless ? .4 : 1;
  $("#abrField").style.pointerEvents = lossless ? "none" : "auto";
}

/* ---------- go ---------- */
$("#goBtn").addEventListener("click", async () => {
  if (!state.info) return;
  toggleSpin("#goBtn", true);
  try {
    const regions = [...state.regions].sort((a, b) => a.start - b.start)
      .map(r => ({ name: r.name, start: r.start, end: r.end }));
    const payload = {
      url: state.info.webpage_url, title: state.info.title,
      mode: state.mode, merge: state.merge,
      audioFormat: state.audioFormat, audioBitrate: state.audioBitrate,
      videoFormat: state.videoFormat, videoBitrate: state.videoBitrate,
      videoQuality: state.videoQuality, regions,
    };
    const { job_id } = await api("/api/process", payload);
    showResult(); pollJob(job_id);
  } catch (e) { alert(e.message); toggleSpin("#goBtn", false); }
});

function showResult() {
  const r = $("#result"); r.hidden = false;
  $("#fileList").innerHTML = ""; $("#resBar").style.width = "0%";
  $("#resBar").classList.remove("done"); $("#resBar").style.background = "";
  $("#resClose").hidden = true;
  r.scrollIntoView({ behavior: "smooth", block: "center" });
}
function pollJob(id) {
  clearInterval(state.poll);
  state.poll = setInterval(async () => {
    let j; try { j = await (await fetch(`/api/progress/${id}`)).json(); } catch { return; }
    $("#resStage").textContent = j.stage || "Working…";
    $("#resMsg").textContent = j.message || "";
    $("#resBar").style.width = (j.progress || 0) + "%";
    if (j.status === "done") {
      clearInterval(state.poll);
      $("#resBar").style.width = "100%"; $("#resBar").classList.add("done");
      $("#resStage").textContent = "✓ Ready"; renderFiles(j.files || []);
      $("#resClose").hidden = false; toggleSpin("#goBtn", false);
    } else if (j.status === "error") {
      clearInterval(state.poll);
      $("#resStage").textContent = "✕ Failed"; $("#resMsg").textContent = j.error || j.message;
      $("#resBar").style.background = "var(--err)"; $("#resClose").hidden = false; toggleSpin("#goBtn", false);
    }
  }, 600);
}
function renderFiles(files) {
  const ul = $("#fileList"); ul.innerHTML = "";
  files.forEach(f => {
    const ext = (f.name.split(".").pop() || "").toUpperCase().slice(0, 4);
    const li = document.createElement("li");
    if (f.is_zip) li.classList.add("zip");
    li.innerHTML = `<div class="fi">${ext}</div>
      <div><div class="fname">${escapeHtml(f.name)}</div><div class="fsize">${fmtSize(f.size)}</div></div>
      <a class="dl" href="${f.url}" download>Download</a>`;
    ul.appendChild(li);
  });
}
$("#resClose").addEventListener("click", () => { $("#result").hidden = true; });

/* ---------- prefill from Chrome extension (?u=<youtube url>) ---------- */
(function initFromQuery() {
  const u = new URLSearchParams(location.search).get("u");
  if (u) {
    $("#url").value = u;
    // wait for the YouTube IFrame API before auto-loading so the player mounts
    const tryLoad = () => { loadUrl(); };
    if (ytReady) tryLoad(); else setTimeout(tryLoad, 900);
  }
})();

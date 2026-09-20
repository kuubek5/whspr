// app.js — KuubWave web UI ("Soft Studio"). State + render + bridge to Python
// (pywebview). Falls back to mock data when opened in a plain browser with no
// pywebview.api, which is how the UI is previewed and verified.
//
// Every api("...") name below must exist as a method on webview_app.py's Api
// class; nothing here may invent a Python method.

const PAGES = { home: "Головна", history: "Історія", dictionary: "Словник", settings: "Налаштування" };
const SUN = '<circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path>';
const MOON = '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z"></path>';

const ICON = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7"/><polyline points="3 4 3 9 8 9"/><polyline points="12 7 12 12 16 14"/>',
  dictionary: '<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v16H6.5A2.5 2.5 0 0 0 4 20.5"/><path d="M4 4.5v16A2.5 2.5 0 0 0 6.5 23H20"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/>',
  mic: '<path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v1a7 7 0 0 1-14 0v-1"/><line x1="12" y1="18" x2="12" y2="22"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  warn: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  shield: '<path d="M12 2 4 5v6c0 5 3.5 8.5 8 11 4.5-2.5 8-6 8-11V5l-8-3Z"/>',
  upd: '<path d="M21 12a9 9 0 1 1-3-6.7"/><polyline points="21 3 21 9 15 9"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  chip: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
  cloud: '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
  key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3 21 2M16 7l3 3M13.5 9.5l2.5 2.5"/>',
  eye: '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M17.9 17.9A10.6 10.6 0 0 1 12 19c-7 0-11-7-11-7a19 19 0 0 1 5-5.9M9.9 4.2A9.7 9.7 0 0 1 12 4c7 0 11 7 11 7a19 19 0 0 1-2.3 3.2M14.1 14.1a3 3 0 1 1-4.2-4.2"/><line x1="2" y1="2" x2="22" y2="22"/>',
  // a display with a small panel floating over — and past — its edge: the overlay itself
  overlay: '<rect x="2.5" y="3.5" width="17" height="12.5" rx="2.5"/><path d="M8 20.5h6M11 16v4.5"/><rect x="12" y="11.5" width="9.5" height="5" rx="2.5"/>',
};
const svg = (p, s = 19) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${p}</svg>`;

const state = {
  theme: "dark", page: "home", homeState: "idle", recordSecs: 0,
  gpu: "…", hotkey: "Fn", listening: false, version: "", update: { available: false },
  license: { licensed: true, daysLeft: 0, exp: "", reason: "ok", customer: "" },
  stats: { wordsToday: 0, dictations: 0, wordsTotal: 0, wpm: 0 },
  recent: [], history: [],
  histQuery: "", histSel: 0, settingsTab: "general",
  // first-run onboarding. `onboarded` comes from bootstrap (defaults true, so an
  // existing user is never interrupted); `onb` is the live wizard state or null.
  onboarded: true, onb: null,
  // quiet-mic warning. micWarnDismissed is session-only by design: a mic that is
  // still too quiet next launch must say so again, so it never goes to config.
  micWarn: { quiet: false, rms: null, canFix: false, level: null },
  micWarnDismissed: false, micWarnFixed: false, micWarnMsg: null,
  settings: { autostart: true, floatingPanel: true, sound: false, autoLang: true,
              model: "uk-ft", gpuDevice: "RTX 4070", device: "cuda", inputDevice: "", micOnDemand: false,
              muteOthers: true, vad: false,
              llm: "off", groqKey: "", groqModel: "", ollamaModel: "",
              groqKeyVisible: false, spokenPunctuation: true, normalizeNumbers: true,
              voiceCommands: true, handsFree: false, llmPrompt: "", llmPromptDefault: "",
              // ---- floating pill placement ----
              // overlayPosition is either one of the nine presets ("bottom-center")
              // or a free {x, y} in percent of the FREE space on each axis — exactly
              // the two shapes flow.py's DEFAULTS documents for overlay_position.
              overlayStyle: "pill", overlayPosition: "bottom-center", overlayScale: 100,
              overlayOpacity: 82,
              // ---- cloud recognition (BYOK) ----
              sttBackend: "local", sttProvider: "groq",
              sttModel: "whisper-large-v3", openaiKey: "", elevenlabsKey: "" },
  devices: [],
  models: [],
  dictionary: { hotwords: "", commands: [] },
};

// ---- bridge ----
const hasApi = () => window.pywebview && window.pywebview.api;
async function api(method, ...args) {
  if (hasApi() && window.pywebview.api[method]) {
    try { return await window.pywebview.api[method](...args); }
    catch (e) { console.warn("api", method, e); }
  }
  return mock(method, args);
}
const MOCK_MODELS = [
  { id: "stock", label: "Large v3 Turbo", size: "1.5 GB", note: "швидка, за замовчуванням", installed: true, active: true, diskMb: 3093 },
  { id: "uk-ft", label: "Large v3 Turbo UA", size: "1.5 GB", note: "донавчена на розмовній українській", installed: true, active: false, diskMb: 3088 },
  { id: "large-v3", label: "Large v3", size: "2.9 GB", note: "найточніша, найповільніша", installed: false, active: false, diskMb: 0 },
  { id: "distil-large-v3", label: "Distil Large v3", size: "1.5 GB", note: "швидша за Large v3", en: true, installed: false, active: false, diskMb: 0 },
  { id: "medium", label: "Medium", size: "1.4 GB", note: "компроміс точність/швидкість", installed: false, active: false, diskMb: 0 },
  { id: "small", label: "Small", size: "465 MB", note: "легка, слабший GPU", installed: false, active: false, diskMb: 0 },
  { id: "base", label: "Base", size: "141 MB", note: "дуже легка, помітно гірша якість", installed: false, active: false, diskMb: 0 },
  { id: "tiny", label: "Tiny", size: "74 MB", note: "найшвидша, найгірша якість", installed: false, active: false, diskMb: 0 },
];

function mock(method, args) {
  if (method === "list_models") return MOCK_MODELS;
  if (method === "activate_model") {
    MOCK_MODELS.forEach((m) => m.active = m.id === args[0] && m.installed);
    return { ok: true };
  }
  if (method === "delete_model") {
    const m = MOCK_MODELS.find((x) => x.id === args[0]);
    if (m) { m.installed = false; m.diskMb = 0; }
    return { ok: true };
  }
  if (method === "download_model") {
    const m = MOCK_MODELS.find((x) => x.id === args[0]);
    if (m) { m.installed = true; m.diskMb = 2048; }
    return { ok: true };
  }
  if (method === "bootstrap") return {
    // Preview the first-run wizard in a plain browser by adding ?onboard to the
    // URL; without it the mock reports an already-onboarded user (no wizard).
    onboarded: !/[?&]onboard\b/.test(location.search),
    theme: "dark", gpu: "RTX 3070", hotkey: "Fn", version: "1.4.4",
    license: { licensed: true, daysLeft: 23, exp: "2026-08-04", reason: "ok", customer: "demo@buyer" },
    status: "idle",
    stats: { wordsToday: 2481, dictations: 37, wordsTotal: 184920, wpm: 132 },
    recent: [
      { time: "Сьогодні, 14:32", text: "зателефонувати Оксані до п'ятниці щодо звіту" },
      { time: "Сьогодні, 13:10", text: "додати пункт про бекапи в документацію" },
      { time: "Сьогодні, 11:48", text: "потрібно оновити прошивку квадрокоптера" },
      { time: "Вчора, 19:20", text: "нагадати купити фотополімер для друку" },
    ],
    history: [
      { id: 5, day: "Сьогодні", time: "14:32", lang: "uk", duration: "3.2с", text: "зателефонувати Оксані до п'ятниці щодо звіту" },
      { id: 4, day: "Сьогодні", time: "13:10", lang: "uk", duration: "2.1с", text: "додати пункт про бекапи в документацію" },
      { id: 3, day: "Сьогодні", time: "11:48", lang: "uk", duration: "1.9с", text: "потрібно оновити прошивку квадрокоптера" },
      { id: 2, day: "Вчора", time: "19:20", lang: "uk", duration: "2.4с", text: "нагадати купити фотополімер для друку" },
      { id: 1, day: "12 вересня", time: "16:05", lang: "en", duration: "3.0с", text: "schedule the standup for tomorrow morning" },
    ],
    settings: state.settings,
    devices: [{ name: "Мікрофон (Realtek Audio)" }, { name: "Вхід (XONAR SOUND CARD)" },
              { name: "OnePlus 9R Hands-Free" }],
    models: MOCK_MODELS,
    dictionary: {
      hotwords: "Klipper, PID, sinter, FPV, Proxmox, homelab, Vaultwarden",
      commands: [
        { phrase: "нова думка", result: "⏎⏎" }, { phrase: "нова строка", result: "⏎" },
        { phrase: "кома", result: "," }, { phrase: "крапка", result: "." },
        { phrase: "знак питання", result: "?" },
      ],
    },
  };
  if (method === "get_status") return state.homeState;
  if (method === "get_download") return { active: false };
  if (method === "get_input_level") return 0.02 + Math.random() * 0.06;
  if (method === "mic_test") return true;
  if (method === "get_mic_warning") return { quiet: false, rms: null, canFix: false, level: null };
  if (method === "fix_mic_level") return { ok: true, before: 0.14, after: 0.85,
    changed: true, reason: "Рівень мікрофона піднято з 14% до 85%." };
  if (method === "check_update") return { available: false, version: "", url: "" };
  if (method === "verify_stt") return { ok: false, message: "(демо) перевірка ключа доступна лише в застосунку" };
  if (method === "get_license") return state.license;
  if (method === "activate_license") return { ok: true, licensed: true, daysLeft: 30, exp: "2026-08-11", reason: "ok" };
  if (method === "save_settings") { console.log("[mock] save_settings", args[0]); return true; }
  if (method === "save_dictionary") { console.log("[mock] save_dictionary", args); return true; }
  if (method === "history_clear") { state.history = []; return true; }
  if (method === "history_delete" || method === "history_copy") return true;
  if (method === "capture_hotkey") return state.hotkey;
  if (method === "finish_onboarding") { console.log("[mock] finish_onboarding"); return true; }
  return null;
}

// ---- boot ----
async function boot() {
  const b = await api("bootstrap");
  state.theme = b.theme || "dark";
  state.gpu = b.gpu || "GPU";
  state.hotkey = b.hotkey || "Fn";
  state.version = b.version || "";
  state.license = b.license || state.license;
  state.stats = b.stats; state.recent = b.recent; state.history = b.history;
  state.settings = Object.assign(state.settings, b.settings || {});
  state.devices = b.devices || [];
  state.models = b.models || [];
  state.dictionary = b.dictionary; state.homeState = b.status || "idle";
  // onboarded may legitimately be false; anything non-boolean means "assume
  // onboarded" so a bridge that predates the flag never traps the user in a wizard
  state.onboarded = (typeof b.onboarded === "boolean") ? b.onboarded : true;
  applyTheme();
  // sidebar shows the local/private status; the exact GPU lives in the hero chip
  document.getElementById("gpuBadge").textContent = "Локально · приватно";
  const vl = document.getElementById("verLine");
  if (vl && state.version) vl.textContent = "v" + state.version;
  paintTopHint();
  renderNav(); render(); pollStatus(); pollDownload(); checkUpdate();
  // the wizard is the first thing a brand-new install sees; the chrome is built
  // above so Home is ready underneath the moment onboarding finishes
  if (state.onboarded === false) openOnboarding();
}
window.addEventListener("pywebviewready", boot);
document.addEventListener("DOMContentLoaded", () => { if (!hasApi()) boot(); });

const esc = (s) => (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const reducedMotion = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion:reduce)").matches;

// ---- toast (role=status, announced politely) ----
let toastTimer = null;
function toast(msg, actLabel, act) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div"); el.id = "toast"; el.className = "toast";
    el.setAttribute("role", "status"); el.setAttribute("aria-live", "polite");
    document.body.appendChild(el);
  }
  el.innerHTML = esc(msg) + (actLabel ? ` <span class="u" id="tundo" role="button" tabindex="0">${esc(actLabel)}</span>` : "");
  if (actLabel) {
    const u = el.querySelector("#tundo");
    const fire = () => { el.classList.remove("show"); if (act) act(); };
    u.onclick = fire;
    u.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fire(); } };
  }
  requestAnimationFrame(() => el.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), actLabel ? 4200 : 1800);
}

// ---- in-world confirm modal: focus-trapped, replaces confirm() for destructive
// actions (clear history, delete a model from disk) ----
function confirmModal({ title, body, confirmLabel, onConfirm }) {
  const prevFocus = document.activeElement;
  const ov = document.createElement("div"); ov.className = "modal-ov";
  ov.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-labelledby="cmTitle" aria-describedby="cmBody">
    <div class="mh"><div class="mi">${svg(ICON.warn, 20)}</div><h3 id="cmTitle">${esc(title)}</h3></div>
    <div class="mb" id="cmBody">${esc(body)}</div>
    <div class="macts">
      <button class="btn ghost" id="cmCancel">Скасувати</button>
      <button class="btn danger" id="cmOk">${esc(confirmLabel)}</button></div></div>`;
  document.body.appendChild(ov);
  const close = () => {
    ov.classList.remove("show"); document.removeEventListener("keydown", onKey);
    setTimeout(() => { ov.remove(); if (prevFocus && prevFocus.focus) prevFocus.focus(); }, 200);
  };
  const onKey = (e) => {
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key === "Tab") {
      const cancel = ov.querySelector("#cmCancel"), ok = ov.querySelector("#cmOk");
      if (e.shiftKey) { if (document.activeElement === cancel) { e.preventDefault(); ok.focus(); } }
      else { if (document.activeElement === ok) { e.preventDefault(); cancel.focus(); } }
    }
  };
  ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(); });
  ov.querySelector("#cmCancel").onclick = close;
  ov.querySelector("#cmOk").onclick = () => { close(); onConfirm(); };
  document.addEventListener("keydown", onKey);
  requestAnimationFrame(() => { ov.classList.add("show"); ov.querySelector("#cmCancel").focus(); });
}

// ---- inline help ("?" toggles an explanatory note) ----
const hbtn = (id) => `<button class="helpbtn" type="button" aria-expanded="false" aria-controls="${id}" aria-label="Що це?" onclick="toggleHelp(this)">?</button>`;
const hnote = (id, txt) => `<div class="helpnote" id="${id}" role="region" hidden>${txt}</div>`;
window.toggleHelp = (b) => {
  const n = document.getElementById(b.getAttribute("aria-controls")); if (!n) return;
  const open = n.hasAttribute("hidden");
  if (open) n.removeAttribute("hidden"); else n.setAttribute("hidden", "");
  b.setAttribute("aria-expanded", open ? "true" : "false");
  b.classList.toggle("on", open);
};

// ---- theme + nav ----
function applyTheme() {
  document.documentElement.setAttribute("data-theme", state.theme);
  document.getElementById("themeIcon").innerHTML = state.theme === "dark" ? SUN : MOON;
  document.getElementById("themeToggle").setAttribute("aria-pressed", state.theme === "dark" ? "true" : "false");
}
document.getElementById("themeToggle").onclick = () => {
  state.theme = state.theme === "dark" ? "light" : "dark";
  applyTheme(); api("set_theme", state.theme);
};
function paintTopHint() {
  const el = document.getElementById("pageTitle");
  if (el) el.innerHTML = `Диктування · затисніть <span class="kb">${esc(state.hotkey)}</span>`;
}
const nav = document.getElementById("nav");
function renderNav() {
  nav.innerHTML = Object.keys(PAGES).map((k) =>
    `<button class="ni${k === state.page ? " on" : ""}" data-page="${k}" aria-current="${k === state.page ? "page" : "false"}">${svg(ICON[k], 19)}<span>${PAGES[k]}</span></button>`).join("");
  nav.querySelectorAll(".ni").forEach((btn) => btn.onclick = () => goto(btn.dataset.page));
}
function goto(page) {
  state.page = page; renderNav(); render();
}
window.goto = goto;

// ---- render dispatch ----
function render() {
  stopMicTest();
  const body = document.getElementById("body");
  body.innerHTML = "";
  const page = document.createElement("div");
  page.className = "page";
  body.appendChild(page);
  ({ home: renderHome, history: renderHistory, dictionary: renderDictionary, settings: renderSettings }[state.page])(page);
}
function emptyBlock(ic, tt, sub) {
  return `<div class="empty"><div class="ei">${svg(ic, 30)}</div><div class="et">${esc(tt)}</div><div class="es">${esc(sub)}</div></div>`;
}

// ================= HOME =================
function renderHome(el) {
  const s = state.stats || { wordsToday: 0, dictations: 0, wordsTotal: 0, wpm: 0 };
  el.innerHTML = `
    <h1 class="htitle">${heroTitle()}</h1>
    <div id="micWarnSlot"></div>
    ${state.update.available ? `<div class="banner upd">
      <div class="ico">${svg(ICON.upd, 17)}</div>
      <div class="bt"><div class="tt">Доступне оновлення v${esc(state.update.version)}</div>
        <div class="bb">Застосунок перезапуститься після встановлення</div></div>
      <button class="btn pri" style="padding:8px 14px" id="updBtn">Оновити</button></div>` : ""}
    <div class="hero" id="hero">
      <span class="blob b1" aria-hidden="true"></span><span class="blob b2" aria-hidden="true"></span>
      <div class="hero-in" id="heroCenter"></div>
    </div>
    <div class="stats">
      ${statTile("слів сьогодні", "wordsToday", "c")}
      ${statTile("диктовок", "dictations", "a")}
      ${statTile("слів усього", "wordsTotal", "v")}
      ${statTile("слів / хв", "wpm", "c")}
    </div>
    <div class="sechead"><h2>Останні диктовки</h2>${state.history.length ? `<button class="lnk" id="allHist">Уся історія →</button>` : ""}</div>
    ${state.recent && state.recent.length ? `<div class="recent">${state.recent.slice(0, 4).map((r) => `
      <div class="rc"><div class="av">${svg(ICON.check, 18)}</div>
        <div class="tx"><div class="t">${esc(r.text)}</div><div class="m mono">${esc(r.time)}</div></div></div>`).join("")}</div>`
      : emptyBlock(ICON.mic, "Ще жодної диктовки", `Затисніть ${state.hotkey} і скажіть кілька слів — ваша перша диктовка зʼявиться тут.`)}`;
  micWarnKey = null;  // fresh slot node — force a paint into it
  renderMicWarning();
  renderHero();
  countUpStats();
  const ub = el.querySelector("#updBtn");
  if (ub) ub.onclick = doInstallUpdate;
  const ah = el.querySelector("#allHist");
  if (ah) ah.onclick = () => goto("history");
  void s;
}
function heroTitle() {
  if (!isLicensed()) return "Ліцензія неактивна";
  if (state.homeState === "recording") return "Слухаю вас…";
  if (state.homeState === "processing") return "Опрацьовую текст…";
  if (state.homeState === "loading") return "Готую модель…";
  return `Готові <span>диктувати</span>?`;
}
function statTile(label, key, tone) {
  return `<div class="st"><div class="n ${tone} mono" data-stat="${key}">0</div><div class="l">${label}</div></div>`;
}
const isLicensed = () => state.license && state.license.licensed;

// ---- hero ----
// The hotkey is the only real way to start a dictation (flow.py owns the
// listener; there is no Api method to start recording from here). So the round
// button is an honest state display with a preview affordance: activating it
// steps the hero through idle → recording → processing so the user can see what
// each state looks like, exactly as the old preview buttons did.
const HERO_CYCLE = { idle: "recording", recording: "processing", processing: "idle", loading: "idle" };
function renderHero() {
  const h = document.getElementById("heroCenter");
  if (!h) return;
  if (!isLicensed()) {
    const expired = state.license && state.license.reason === "expired";
    h.innerHTML = `<div class="recbtn" role="img" aria-label="Ліцензія неактивна">${svg(ICON.key, 42)}</div>
      <div class="hero-tx"><div class="k">${expired ? "Ліцензію прострочено" : "Ліцензія неактивна"}</div>
        <div class="s">Введіть ключ у Налаштуваннях → Ліцензія, щоб знову диктувати.</div></div>`;
    return;
  }
  const previewNote = "Диктування запускається клавішею " + state.hotkey + "; тут можна лише подивитися вигляд станів";
  if (state.homeState === "recording") {
    h.innerHTML = `<div class="recbtn live" role="button" tabindex="0" aria-pressed="true"
        aria-label="Запис. ${esc(previewNote)}">${svg(ICON.mic, 42)}</div>
      <div class="hero-tx"><div class="timer mono">${fmtTime(state.recordSecs)}</div>
        <div class="reclabel"><span class="recdot"></span>Запис · відпустіть <span class="key" style="padding:3px 9px">${esc(state.hotkey)}</span>, щоб завершити</div>
        <div class="wavelane" id="wl" aria-hidden="true"></div></div>`;
  } else if (state.homeState === "processing") {
    h.innerHTML = `<div class="recbtn" role="button" tabindex="0" aria-pressed="false"
        aria-label="Розпізнавання. ${esc(previewNote)}">${svg(ICON.mic, 42)}</div>
      <div class="hero-tx"><div class="proc"><div class="sk" style="width:78%"></div><div class="sk" style="width:52%"></div>
        <div style="font-size:13.5px;color:rgba(255,255,255,.9);margin-top:4px">Розпізнаю мовлення на GPU…</div></div></div>`;
  } else if (state.homeState === "loading") {
    h.innerHTML = `<div class="recbtn" role="button" tabindex="0" aria-pressed="false"
        aria-label="Завантаження моделі. ${esc(previewNote)}">${svg(ICON.mic, 42)}</div>
      <div class="hero-tx"><div class="k">Завантаження моделі…</div>
        <div class="s">За мить усе буде готово — модель шукається на диску або качається.</div>
        <div class="dl-wrap" id="dlProgress" style="display:none"><div class="dl-bar"><div class="dl-fill indet"></div></div><div class="dl-text"></div></div></div>`;
  } else {
    h.innerHTML = `<div class="recbtn idle" role="button" tabindex="0" aria-pressed="false"
        aria-label="Очікування. ${esc(previewNote)}">${svg(ICON.mic, 42)}</div>
      <div class="hero-tx"><div class="k">Затисніть <span class="key">${esc(state.hotkey)}</span> і говоріть</div>
        <div class="s">${state.settings.sttBackend === "cloud"
          ? "Диктуйте будь-де на екрані. Хмарне розпізнавання — аудіо йде на сервери провайдера."
          : "Диктуйте будь-де на екрані. Розпізнавання йде на вашому GPU — жодне слово не залишає цей компʼютер."}</div>
        <div class="wavelane" id="wl" aria-hidden="true"></div>
        <div class="hero-row">
          ${state.settings.sttBackend === "cloud"
            ? `<div class="hc"><span class="k2">Хмара</span><span class="v">${esc((STT_PROVIDERS[state.settings.sttProvider] || {}).label || "Cloud")}</span></div>`
            : `<div class="hc"><span class="k2">Пристрій</span><span class="v">${esc(state.gpu)}</span></div>`}
          <div class="hc"><span class="k2">Мова</span><span class="v">${state.settings.autoLang ? "UK · авто" : "UK"}</span></div>
          <div class="hc"><span class="k2">Клавіша</span><span class="v">${esc(state.hotkey)}</span></div>
        </div></div>`;
  }
  fillWave();
  const btn = h.querySelector(".recbtn[role='button']");
  if (btn) {
    const step = () => {
      state.manualHoldUntil = Date.now() + 6000;  // let the manual preview stay ~6s
      setHomeState(HERO_CYCLE[state.homeState] || "idle");
      // renderHero() has already replaced this node, so move focus onto the new
      // one right away — a rAF hop would be dropped while the window is hidden
      const again = document.querySelector("#heroCenter .recbtn[role='button']");
      if (again) again.focus();
    };
    btn.onclick = step;
    btn.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") { e.preventDefault(); step(); }
    };
  }
  if (state.homeState === "loading") tickDownload();
}
function fillWave() {
  const wl = document.getElementById("wl");
  if (!wl) return;
  wl.innerHTML = waveBars(46);
}
function waveBars(n) {
  let s = "";
  for (let i = 0; i < n; i++) {
    const h = 22 + Math.random() * 78, dur = 1 + Math.random() * 0.8;
    s += `<div class="wl" style="height:${h.toFixed(1)}%;animation-delay:-${(i * 0.05).toFixed(2)}s;animation-duration:${dur.toFixed(2)}s"></div>`;
  }
  return s;
}
const fmtTime = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
let recTimer = null;
function setHomeState(s) {
  state.homeState = s;
  if (s === "recording") {
    state.recordSecs = 0; clearInterval(recTimer);
    recTimer = setInterval(() => {
      state.recordSecs++;
      const t = document.querySelector(".timer");
      if (t) t.textContent = fmtTime(state.recordSecs);
    }, 1000);
  } else clearInterval(recTimer);
  if (state.page === "home") {
    const h = document.querySelector(".htitle");
    if (h) h.innerHTML = heroTitle();
    renderHero();
    heroRipple(s);
  }
}
// crisp press feedback on the record button only; never an entrance animation
function heroRipple(next) {
  if (reducedMotion() || next !== "recording") return;
  const hero = document.getElementById("hero"), btn = hero && hero.querySelector(".recbtn");
  if (!hero || !btn) return;
  const hr = hero.getBoundingClientRect(), br = btn.getBoundingClientRect();
  const r = document.createElement("span"); r.className = "hero-ripple";
  r.style.left = (br.left - hr.left + br.width / 2) + "px";
  r.style.top = (br.top - hr.top + br.height / 2) + "px";
  hero.appendChild(r);
  const a = r.animate([{ transform: "scale(.22)", opacity: .85 }, { transform: "scale(1)", opacity: 0 }],
    { duration: 640, easing: "cubic-bezier(.16,1,.3,1)" });
  a.onfinish = () => r.remove(); a.oncancel = () => r.remove();
}
function countUpStats() {
  const targets = state.stats || {};
  const paint = (mult) => document.querySelectorAll("[data-stat]").forEach((el) => {
    el.textContent = Math.round((targets[el.dataset.stat] || 0) * mult).toLocaleString("uk");
  });
  if (reducedMotion()) { paint(1); return; }
  const dur = 1200, start = performance.now();
  function step(now) {
    const p = Math.min(1, (now - start) / dur), e = 1 - Math.pow(1 - p, 3);
    paint(e);
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// ---- download progress (hero, "loading" state) ----
async function tickDownload() {
  const box = document.getElementById("dlProgress");
  if (!box) return;
  const d = await api("get_download");
  if (d && d.active) {
    const bar = box.querySelector(".dl-fill");
    const txt = box.querySelector(".dl-text");
    // scaleX, not width — see .dl-fill in index.html. The inline transform must
    // be cleared when handing the bar back to the indeterminate sweep, or it
    // would sit on top of the keyframes' own transform.
    if (d.pct != null) {
      bar.classList.remove("indet");
      bar.style.transform = `scaleX(${Math.max(0, Math.min(1, d.pct / 100))})`;
    } else {
      bar.classList.add("indet");
      bar.style.transform = "";
    }
    const size = d.totalMb ? `${d.mb} / ${d.totalMb} МБ` : (d.mb ? `${d.mb} МБ` : "");
    txt.textContent = [d.label, size].filter(Boolean).join(" · ");
    box.style.display = "block";
  } else box.style.display = "none";
}
function pollDownload() {
  // window hidden = closed to tray; the WebView2 process lives on, so skip the
  // bridge call instead of hammering Python 2x/s to paint nothing
  setInterval(() => { if (document.hidden) return; tickDownload(); }, 500);
}

// ---- quiet mic warning ----
// flow.py raises mic_too_quiet when its software boost pins at the ceiling: that
// take amplified room noise as much as speech, which is where the hallucinated
// text and one-word transcripts come from. Say it out loud instead of only in
// the log, and offer the one fix that actually works (the Windows input level).
// When the Windows slider is already at the top and the signal is still weak,
// raising it is a no-op — the remaining headroom sits in the driver's separate
// "Microphone Boost", or the mic is simply too far away. Say that instead of
// offering a button that answers "уже достатньо гучний" and leaves the user stuck.
const MIC_FALLBACK = "Гучність мікрофона вже на максимумі, але сигнал слабкий. "
  + "Перевірте «Підсилення мікрофона» (Microphone Boost) у драйвері звуку "
  + "(Звук → Ввід → Властивості → Рівні) або підсуньте мікрофон ближче.";
let micWarnKey = null;
function renderMicWarning() {
  const slot = document.getElementById("micWarnSlot");
  if (!slot) return;  // not on Home
  const w = state.micWarn || {};
  const show = !!w.quiet && !state.micWarnDismissed && !state.micWarnFixed;
  // repaint only when something the banner shows actually changed — the poll
  // must not rebuild the node under the user's cursor mid-click
  const key = show ? `${w.rms}|${w.canFix}|${w.level}|${state.micWarnMsg}` : "";
  if (key === micWarnKey) return;
  micWarnKey = key;
  if (!show) { slot.innerHTML = ""; return; }
  // rms lands only after a measured take, and mic_level is optional — degrade
  // to plain advice rather than promising a button that cannot exist
  const lvl = typeof w.rms === "number" ? ` Рівень сигналу — ${w.rms.toFixed(4)}.` : "";
  const atMax = typeof w.level === "number" && w.level >= 0.9;
  const canFix = !!w.canFix && !atMax;
  const advice = atMax ? " " + MIC_FALLBACK
    : (canFix ? "" : " Підніміть гучність мікрофона у Windows: Звук → Ввід → Властивості → Рівні.");
  const body = state.micWarnMsg
    || `Звук підсилюється програмно до межі — це додає шум і спричиняє помилки розпізнавання.${lvl}${advice}`;
  slot.innerHTML = `<div class="banner warn" role="status">
    <div class="ico">${svg(ICON.warn, 17)}</div>
    <div class="bt"><div class="tt">Мікрофон записує надто тихо</div>
      <div class="bb" id="micWarnBody">${esc(body)}</div></div>
    ${canFix && !state.micWarnMsg ? `<button class="btn ghost" style="padding:8px 14px" id="micFixBtn">Підняти рівень</button>` : ""}
    <button class="x" id="micWarnX" aria-label="Приховати">✕</button>
  </div>`;
  slot.querySelector("#micWarnX").onclick = () => {
    state.micWarnDismissed = true; renderMicWarning();
  };
  const fix = slot.querySelector("#micFixBtn");
  if (fix) fix.onclick = () => fixMicLevel(fix);
}
async function fixMicLevel(btn) {
  btn.disabled = true; btn.textContent = "Піднімаю…";
  const r = (await api("fix_mic_level")) || {};
  const reason = r.reason || "Не вдалося змінити гучність мікрофона.";
  // ok but nothing changed = the slider was already up and the signal is still
  // weak. That is not "solved"; keep the banner and hand over the real next step.
  state.micWarnMsg = (r.ok && !r.changed) ? `${reason} ${MIC_FALLBACK}` : reason;
  micWarnKey = null;
  renderMicWarning();
  // mic_too_quiet only clears on the next take, so close the banner ourselves —
  // after a beat, so the user gets to read what the fix actually did
  if (r.ok && r.changed) setTimeout(() => {
    state.micWarnFixed = true; renderMicWarning();
  }, 2800);
}
async function tickMicWarning() {
  const w = await api("get_mic_warning");
  if (!w) return;
  state.micWarn = w;
  // a take that no longer needs heavy boost means the fix took: forget the
  // result text and re-arm the banner in case the mic drifts quiet again.
  // An explicit ✕ is not re-armed — that one is the user's call for the session.
  if (!w.quiet) { state.micWarnMsg = null; state.micWarnFixed = false; }
  renderMicWarning();
}

// ---- update check ----
async function checkUpdate() {
  const u = await api("check_update");
  state.update = u || { available: false };
  if (state.update.available && state.page === "home") render();
}
function doInstallUpdate() {
  confirmModal({
    title: `Оновити до v${state.update.version}?`,
    body: "KuubWave завантажить оновлення і перезапуститься. Незбережені зміни в налаштуваннях краще застосувати зараз.",
    confirmLabel: "Оновити",
    onConfirm: () => api("install_update", state.update.url),
  });
}
// manual "check now" from Settings: same check as on boot, but always speaks —
// offers the install if there is one, otherwise confirms you are up to date
async function checkUpdateManual(btn) {
  const label = btn && btn.textContent;
  if (btn) { btn.disabled = true; btn.textContent = "Перевіряю…"; }
  try {
    const u = await api("check_update");
    state.update = u || { available: false };
    if (state.update.available) doInstallUpdate();
    else toast(`У вас найновіша версія${state.version ? " (v" + state.version + ")" : ""}`);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label || "Перевірити оновлення"; }
  }
}

// ================= HISTORY =================
// Day grouping keys off the real calendar day the bridge sends per row
// (h.day: "Сьогодні" / "Вчора" / "12 вересня"), so buckets are exact rather
// than guessed from the clock.
function histFiltered() {
  const q = (state.histQuery || "").trim().toLowerCase();
  return (state.history || []).map((h, idx) => Object.assign({ _idx: idx }, h))
    .filter((h) => !q || (h.text || "").toLowerCase().includes(q));
}
function renderHistory(el) {
  el.innerHTML = `<h1 class="htitle">Історія</h1>`;
  if (!state.history.length) {
    el.insertAdjacentHTML("beforeend", emptyBlock(ICON.history, "Історія порожня", "Ваші диктовки зʼявлятимуться тут"));
    return;
  }
  el.insertAdjacentHTML("beforeend", `
    <div class="hist-top">
      <span class="cnt"><span class="pill mono">${state.history.length}</span>диктовок</span>
      <button class="btn-danger" id="hclear">${svg(ICON.trash, 14)}Очистити все</button></div>
    <div class="hist-two">
      <div class="hist-col">
        <div class="hist-search">${svg(ICON.search, 16)}
          <input id="hsearch" placeholder="Пошук у диктовках…" value="${esc(state.histQuery)}" aria-label="Пошук у диктовках">
          <button class="clr ${state.histQuery ? "show" : ""}" id="hclr" aria-label="Очистити пошук">✕</button></div>
        <div class="hist-list" id="hlist" role="listbox" tabindex="0" aria-label="Диктовки"></div>
      </div>
      <div class="hist-detail" id="hdetail"></div>
    </div>`);
  const s = el.querySelector("#hsearch");
  s.oninput = () => {
    state.histQuery = s.value; state.histSel = 0;
    el.querySelector("#hclr").classList.toggle("show", !!s.value);
    drawHistList(); drawHistDetail();
  };
  el.querySelector("#hclr").onclick = () => {
    state.histQuery = ""; s.value = ""; state.histSel = 0;
    el.querySelector("#hclr").classList.remove("show"); s.focus();
    drawHistList(); drawHistDetail();
  };
  el.querySelector("#hclear").onclick = () => confirmModal({
    title: "Очистити історію?",
    body: "Усі диктовки буде видалено з цього пристрою. Цю дію не можна скасувати.",
    confirmLabel: "Очистити все",
    onConfirm: async () => {
      await api("history_clear");
      state.history = []; state.recent = []; state.histQuery = ""; state.histSel = 0;
      renderHistory(el);
      toast("Історію очищено");
    },
  });
  const list = el.querySelector("#hlist");
  list.onkeydown = (e) => {
    const f = histFiltered(); if (!f.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); state.histSel = Math.min(f.length - 1, state.histSel + 1); drawHistList(true); drawHistDetail(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); state.histSel = Math.max(0, state.histSel - 1); drawHistList(true); drawHistDetail(); }
    else if (e.key === "Enter") { e.preventDefault(); copyCurrent(); }
  };
  drawHistList(); drawHistDetail();
}
function drawHistList(scroll) {
  const l = document.getElementById("hlist"); if (!l) return;
  const f = histFiltered();
  if (state.histSel >= f.length) state.histSel = Math.max(0, f.length - 1);
  if (!f.length) {
    l.innerHTML = `<div class="empty" style="padding:40px 16px"><div class="ei">${svg(ICON.search, 26)}</div>
      <div class="et">Нічого не знайдено</div><div class="es">Спробуйте інший запит</div></div>`;
    return;
  }
  let html = "", lastLabel = null;
  f.forEach((h, i) => {
    const label = h.day || "—";
    if (label !== lastLabel) {
      lastLabel = label;
      html += `<div class="day-head ${label === "Сьогодні" ? "today" : ""}"><span class="ddot"></span>${esc(label)}</div>`;
    }
    const en = (h.lang || "uk").toLowerCase() === "en";
    html += `<div class="lrow ${i === state.histSel ? "on kbd" : ""}" role="option" aria-selected="${i === state.histSel}" data-i="${i}">
      <div class="lav ${en ? "en" : ""}">${svg(ICON.mic, 16)}</div>
      <div class="lbd"><div class="lt">${esc(h.text)}</div>
        <div class="lm"><span class="mono">${esc(h.time)}</span><span class="tag ${en ? "v" : ""}">${esc((h.lang || "uk").toUpperCase())}</span><span>${esc(h.duration)}</span></div></div></div>`;
  });
  l.innerHTML = html;
  l.querySelectorAll(".lrow").forEach((r) => r.onclick = () => {
    state.histSel = +r.dataset.i; drawHistList(); drawHistDetail();
  });
  if (scroll) { const on = l.querySelector(".lrow.on"); if (on) on.scrollIntoView({ block: "nearest" }); }
}
const currentHist = () => histFiltered()[state.histSel];
function drawHistDetail() {
  const d = document.getElementById("hdetail"); if (!d) return;
  const h = currentHist();
  if (!h) { d.innerHTML = ""; return; }
  const words = ((h.text || "").trim().match(/\S+/g) || []).length, chars = (h.text || "").length;
  const active = (state.models || []).find((m) => m.active);
  const en = (h.lang || "uk").toLowerCase() === "en";
  d.innerHTML = `
    <div class="dmeta"><span class="datechip mono">${esc(h.day ? h.day + ", " + h.time : h.time)}</span>
      <span class="tag ${en ? "v" : ""}">${esc((h.lang || "uk").toUpperCase())}</span><span>${esc(h.duration)}</span></div>
    <div class="dtx">${esc(h.text)}</div>
    <div class="dstats">
      <span class="ds"><b>${words}</b> слів</span>
      <span class="ds"><b>${chars}</b> символів</span>
      ${active ? `<span class="ds">${esc(active.label)}</span>` : ""}</div>
    <div class="dacts">
      <button class="btn pri" id="dCopy">${svg(ICON.copy, 15)}Копіювати</button>
      <button class="btn ghost" id="dDel">${svg(ICON.trash, 15)}Видалити</button></div>`;
  d.querySelector("#dCopy").onclick = () => copyCurrent();
  d.querySelector("#dDel").onclick = () => deleteCurrent();
}
function copyCurrent() {
  const h = currentHist(); if (!h) return;
  api("history_copy", h.id);
  const b = document.querySelector("#dCopy");
  if (b) {
    const o = b.innerHTML;
    b.innerHTML = svg(ICON.check, 15) + "Копіювати";
    if (!reducedMotion()) { b.classList.remove("pop"); void b.offsetWidth; b.classList.add("pop"); }
    setTimeout(() => { const bb = document.querySelector("#dCopy"); if (bb) { bb.innerHTML = o; bb.classList.remove("pop"); } }, 1200);
  }
  toast("Скопійовано");
}
function deleteCurrent() {
  const h = currentHist(); if (!h) return;
  // the row is gone from the database the moment it is deleted, so there is no
  // undo to offer here — history_delete on the Python side is final
  api("history_delete", h.id);
  state.history = state.history.filter((x) => x.id !== h.id);
  state.recent = (state.recent || []).filter((r) => r.text !== h.text);
  const page = document.querySelector(".page");
  if (page) renderHistory(page);
  toast("Диктовку видалено");
}

// ================= DICTIONARY =================
const hwList = () => (state.dictionary.hotwords || "").split(",").map((s) => s.trim()).filter(Boolean);
function renderDictionary(el) {
  el.innerHTML = `<h1 class="htitle">Словник</h1>
    <div class="panel">
      <div class="dhead"><div class="di c">${svg(ICON.dictionary, 20)}</div>
        <h2 class="lab-h">Хотворди${hbtn("hlp-hotwords")}</h2>
        <span class="cnt" id="hwCnt">0 термінів</span></div>
      <div class="desc">Терміни, які модель має розпізнавати з підвищеним пріоритетом</div>
      ${hnote("hlp-hotwords", "Хотворди — це рідкісні слова й терміни (назви, бренди, жаргон), які модель часто чує неправильно. Додайте їх сюди, і розпізнавання віддаватиме їм перевагу.")}
      <div class="hw-chips" id="hwchips"></div>
      <div class="hw-add">${svg(ICON.plus, 16)}<input id="hwadd" placeholder="Додати термін і натиснути Enter…" aria-label="Додати термін"></div>
    </div>
    <div class="panel">
      <div class="dhead"><div class="di a">${svg(ICON.mic, 20)}</div><h2>Голосові команди</h2>
        <button class="addbtn" id="cmdAdd">${svg(ICON.plus, 14)}Додати</button></div>
      <div class="desc">Промовте фразу зліва — KuubWave вставить символ праворуч. Наприклад: «нова думка» = ⏎</div>
      <div class="cmd-list" id="cmdlist"></div>
    </div>
    <div class="dict-save"><button class="btn pri" id="dictSave">Зберегти</button></div>`;
  drawHotwords(); drawCmds();
  const add = el.querySelector("#hwadd");
  add.onkeydown = (e) => {
    if (e.key !== "Enter" && e.key !== ",") return;
    e.preventDefault();
    const v = add.value.trim().replace(/,$/, "");
    if (v) {
      const l = hwList();
      if (!l.some((x) => x.toLowerCase() === v.toLowerCase())) {
        l.push(v); state.dictionary.hotwords = l.join(", "); drawHotwords();
        const chips = document.querySelectorAll("#hwchips .hw-chip");
        const last = chips[chips.length - 1];
        if (last && !reducedMotion()) last.classList.add("pop");
      }
    }
    add.value = "";
  };
  el.querySelector("#cmdAdd").onclick = () => {
    state.dictionary.commands.push({ phrase: "", result: "" }); drawCmds();
    const rows = document.querySelectorAll("#cmdlist .crow");
    const last = rows[rows.length - 1];
    if (last) last.querySelector(".p").focus();
  };
  el.querySelector("#dictSave").onclick = async () => {
    await api("save_dictionary", state.dictionary.hotwords, state.dictionary.commands);
    toast("Словник збережено");
  };
}
function drawHotwords() {
  const c = document.getElementById("hwchips"); if (!c) return;
  const hw = hwList();
  const cnt = document.getElementById("hwCnt");
  if (cnt) cnt.textContent = `${hw.length} термінів`;
  if (!hw.length) { c.innerHTML = `<div class="dict-empty" style="width:100%">Ще немає термінів</div>`; return; }
  c.innerHTML = hw.map((w, i) => `<span class="hw-chip">${esc(w)}<button class="x" data-i="${i}" aria-label="Видалити ${esc(w)}">✕</button></span>`).join("");
  c.querySelectorAll(".x").forEach((b) => b.onclick = () => {
    const l = hwList(); l.splice(+b.dataset.i, 1);
    state.dictionary.hotwords = l.join(", "); drawHotwords();
  });
}
function drawCmds() {
  const l = document.getElementById("cmdlist"); if (!l) return;
  if (!state.dictionary.commands.length) { l.innerHTML = `<div class="dict-empty">Ще немає команд — додайте першу</div>`; return; }
  l.innerHTML = state.dictionary.commands.map((c, i) => `<div class="crow" data-i="${i}">
    <input class="inp p mono" value="${esc(c.phrase)}" placeholder="фраза" aria-label="Фраза">
    <span class="eq" aria-hidden="true">=</span>
    <input class="inp r" value="${esc(c.result)}" placeholder="символ" aria-label="Результат">
    <button class="mini del" aria-label="Видалити команду">${svg(ICON.trash, 14)}</button></div>`).join("");
  l.querySelectorAll(".crow").forEach((row) => {
    const i = +row.dataset.i;
    row.querySelector(".p").oninput = (e) => (state.dictionary.commands[i].phrase = e.target.value);
    row.querySelector(".r").oninput = (e) => (state.dictionary.commands[i].result = e.target.value);
    row.querySelector(".del").onclick = () => { state.dictionary.commands.splice(i, 1); drawCmds(); };
  });
}

// ================= SETTINGS =================
const STABS = [["general", "Загальні", ICON.settings], ["floating", "Панель", ICON.overlay],
               ["mic", "Мікрофон", ICON.mic], ["model", "AI", ICON.chip],
               ["license", "Ліцензія", ICON.key]];

// Cloud recognition providers (BYOK). Curated model lists — we vetted these for
// Ukrainian dictation; prices are indicative (the provider is the source of truth).
const STT_PROVIDERS = {
  groq: { label: "Groq", free: true, keyUrl: "https://console.groq.com/keys",
    reuseGroqKey: true,
    models: [
      { id: "whisper-large-v3", label: "Whisper large-v3", badges: ["точна", "≈$0.04/год"] },
      { id: "whisper-large-v3-turbo", label: "Whisper large-v3 turbo", badges: ["швидка", "дешевша"] },
    ] },
  openai: { label: "OpenAI", free: false, keyProp: "openaiKey", keyUrl: "https://platform.openai.com/api-keys",
    models: [
      { id: "gpt-transcribe", label: "gpt-transcribe", badges: ["найточніша"] },
      { id: "gpt-4o-mini-transcribe", label: "gpt-4o-mini-transcribe", badges: ["дешевша"] },
      { id: "whisper-1", label: "whisper-1", badges: ["легасі", "найдешевша"] },
    ] },
  elevenlabs: { label: "ElevenLabs", free: true, keyProp: "elevenlabsKey", keyUrl: "https://elevenlabs.io/app/settings/api-keys",
    models: [
      { id: "scribe_v2", label: "Scribe v2", badges: ["найкраща укр"] },
    ] },
};
function sttProvider() { return STT_PROVIDERS[state.settings.sttProvider] || STT_PROVIDERS.groq; }
function sttModeCard(id, title, icon, sub) {
  const on = state.settings.sttBackend === id;
  return `<button class="mode-card${on ? " on" : ""}" data-stt="${id}" role="radio"
      aria-checked="${on ? "true" : "false"}" aria-label="${esc(title)} — ${esc(sub)}">
      <span class="mc-ic">${svg(icon, 20)}</span>
      <span class="mc-tx"><span class="mc-t">${esc(title)}</span><span class="mc-s">${esc(sub)}</span></span>
      <span class="mc-check">${svg(ICON.check, 13)}</span></button>`;
}
function sttModelBadgesHtml() {
  const p = sttProvider();
  const m = p.models.find((x) => x.id === state.settings.sttModel) || p.models[0];
  return (m.badges || []).map((b) => `<span class="stt-badge">${esc(b)}</span>`).join("");
}
function sttProviderOptions() {
  return Object.entries(STT_PROVIDERS).map(([id, p]) =>
    `<option value="${id}"${state.settings.sttProvider === id ? " selected" : ""}>${esc(p.label)}${p.free ? " · безкоштовний ліміт" : ""}</option>`).join("");
}
function sttModelOptions() {
  return sttProvider().models.map((m) =>
    `<option value="${m.id}"${state.settings.sttModel === m.id ? " selected" : ""}>${esc(m.label)}</option>`).join("");
}
function sttKeyRowHtml() {
  const p = sttProvider();
  if (p.reuseGroqKey) {
    return `<div class="cloud-hint">Ключ спільний із поліруванням Groq (нижче) — другий не потрібен.</div>`;
  }
  return `<div class="crow"><span class="crow-l">Ключ ${esc(p.label)}</span>
    <span class="crow-r key-wrap"><input class="inp mono" id="${p.keyProp}" type="password" value="${esc(state.settings[p.keyProp] || "")}" placeholder="ключ…" aria-label="API-ключ ${esc(p.label)}"></span></div>`;
}
function sttCloudHtml() {
  const p = sttProvider();
  return `<div class="cloud-card">
    <div class="cloud-warn">${svg(ICON.warn, 15)}<span>Аудіо йде на сервери провайдера. Локальні укр-переваги вимкнено.</span></div>
    <div class="crow"><span class="crow-l">Сервіс</span>
      <span class="crow-r"><select class="sel" id="sttProvider" aria-label="Сервіс розпізнавання">${sttProviderOptions()}</select>
        <a class="lnk" id="sttKeyLink" href="${p.keyUrl}" target="_blank" rel="noopener">Отримати ключ →</a></span></div>
    <div id="sttKeyRow">${sttKeyRowHtml()}</div>
    <div class="crow"><span class="crow-l">Модель</span>
      <span class="crow-r"><select class="sel" id="sttModel" aria-label="Модель розпізнавання">${sttModelOptions()}</select></span></div>
    <div class="stt-badges" id="sttBadges">${sttModelBadgesHtml()}</div>
    <div class="cloud-foot">
      <button class="btn pri" id="sttVerify">Перевірити ключ</button>
      <span class="cloud-price">${p.free ? "Є безкоштовний ліміт · ціни у провайдера" : "Ціни у провайдера"}</span></div>
    <div class="note" id="sttVerifyNote" style="display:none;margin-top:2px"></div></div>`;
}
function toggleRow(label, hint, key, help) {
  const on = state.settings[key];
  return `<div class="srow"><div style="min-width:0">
      <div class="lab lab-h">${label}${help ? hbtn(help[0]) : ""}</div>
      <div class="hint">${hint}</div>${help ? hnote(help[0], help[1]) : ""}</div>
    <button class="tg ${on ? "on" : ""}" role="switch" aria-checked="${on ? "true" : "false"}"
      aria-label="${esc(label)}" data-key="${key}"><span class="th"></span></button></div>`;
}
function renderSettings(el) {
  const s = state.settings, tab = state.settingsTab;
  const panes = {
    general: `
      <div class="panel"><h2>Запуск</h2>
        ${toggleRow("Запускати з Windows", "Автоматично запускати KuubWave при вході в систему", "autostart")}
        ${toggleRow("Звук при завершенні диктовки", "Короткий сигнал, коли текст готовий", "sound")}</div>
      <div class="panel"><h2>Поведінка</h2>
        ${toggleRow("Голосові команди", "«великими літерами», «видали останнє», «переклади англійською» — діють на попередню диктовку", "voiceCommands")}
        ${toggleRow("Режим без утримання", "Тап клавіші вмикає запис, авто-стоп після паузи (або тап ще раз). Інакше — утримувати клавішу", "handsFree",
          ["hlp-handsfree", "Зазвичай ви утримуєте клавішу, поки говорите. У режимі без утримання один тап вмикає запис, а він сам зупиняється після паузи — зручно для довгих диктовок."])}</div>
      <div class="panel"><h2>Гаряча клавіша</h2>
        <div class="hkwrap"><span class="keycap" id="hkCap">${esc(state.hotkey)}</span>
          <button class="btn ghost" id="hotkeyBtn">Змінити</button></div>
        <div class="hint" style="margin-top:14px">Утримувати для диктування — натисніть «Змінити» та виконайте потрібну комбінацію</div></div>
      <div class="panel"><h2>Оновлення</h2>
        <div class="srow"><div style="min-width:0">
            <div class="lab">Версія ${state.version ? "v" + esc(state.version) : "—"}</div>
            <div class="hint">KuubWave перевіряє оновлення сам при запуску й пропонує встановити нову версію</div></div>
          <button class="btn ghost" id="chkUpdBtn">Перевірити оновлення</button></div></div>`,
    floating: floatingPanel(),
    mic: `
      <div class="panel"><h2>Мікрофон</h2>
        <div class="srow"><div style="min-width:0"><div class="lab">Пристрій вводу</div><div class="hint">Джерело звуку для диктування</div></div>
          <select class="sel" id="selMic" aria-label="Пристрій вводу"></select></div>
        ${toggleRow("Відкривати мікрофон лише під час запису", "Прибирає значок мікрофона в треї; можливе зрізання перших мілісекунд фрази", "micOnDemand")}
        ${toggleRow("Глушити інші звуки під час запису", "Музика, відео та сповіщення стихають, поки ви диктуєте, і вмикаються назад після відпускання клавіші", "muteOthers")}
        ${toggleRow("Вирізати тишу перед розпізнаванням", "Прибирає паузи, на яких модель вигадує текст. Якщо мікрофон тихий — може різати мовлення, тоді вимкніть.", "vad",
          ["hlp-vad", "«Вирізати тишу» (VAD) прибирає паузи без голосу перед розпізнаванням. Плюс — модель не вигадує слова в тиші. Мінус — може обрізати дуже тихий початок фрази."])}
        <div class="mic"><button class="btn ghost" id="micTestBtn">Перевірити</button>
          <div class="level"><div class="fill" id="levelFill"></div><div class="th"></div></div></div>
        <div class="hint" id="micHint" style="margin-top:12px"></div></div>`,
    model: `
      <div class="panel"><h2 class="lab-h">Розпізнавання${hbtn("hlp-model")}</h2>
        <div class="desc">Оберіть, де розпізнавати мовлення — активний спосіб підсвічено</div>
        ${hnote("hlp-model", "Локально — приватно, на вашому GPU/CPU, з українським fine-tune. Хмара — швидко й без GPU, але аудіо йде на сервери провайдера, і локальні укр-переваги не діють.")}
        <div class="mode-grid" id="sttModes" role="radiogroup" aria-label="Спосіб розпізнавання">
          ${sttModeCard("local", "Локально", ICON.chip, "Приватно · на вашому GPU · укр-переваги")}
          ${sttModeCard("cloud", "Хмара", ICON.cloud, "Швидко · без GPU · свій ключ")}
        </div>
        <div id="sttLocal"${s.sttBackend === "cloud" ? " hidden" : ""}>
          <div class="mcards" id="mcards" role="radiogroup" aria-label="Модель розпізнавання" style="margin-top:14px"></div>
          <div class="srow" style="margin-top:6px"><div style="min-width:0"><div class="lab">Пристрій обробки</div>
              <div class="hint">Де рахувати модель: GPU швидко, CPU повільний запасний. Уся обробка локально</div></div>
            <select class="sel" id="selGpu" aria-label="Пристрій обробки">
              <option value="cuda">${esc(state.gpu)} (GPU)</option>
              <option value="cpu">CPU (запасний варіант)</option></select></div></div>
        <div id="sttCloud"${s.sttBackend === "local" ? " hidden" : ""} style="margin-top:14px">${sttCloudHtml()}</div>
      </div>`,
    ai: `
      <div class="panel"><h2>Мова та пунктуація</h2>
        ${toggleRow("Автоматичне визначення мови", "KuubWave сам визначить українську чи англійську", "autoLang")}
        ${toggleRow("Голосова пунктуація", "Слова «кома», «крапка», «знак питання» стають , . ?", "spokenPunctuation")}
        ${toggleRow("Числа цифрами", "«триста пʼятдесят два» → «352»", "normalizeNumbers")}</div>
      <div class="panel"><h2>Полірування тексту (AI)</h2>
        <div class="desc">Прибирає слова-паразити, розставляє пунктуацію. Виконується після розпізнавання</div>
        <div class="cloud-warn" role="note" style="margin:2px 0 6px">${svg(ICON.warn, 15)}<span>У режимі Groq текст диктовок іде на сервери Groq для полірування. Ollama — локально.</span></div>
        <div class="srow"><div style="min-width:0"><div class="lab lab-h">Режим${hbtn("hlp-ai")}</div>
            <div class="hint">Ollama — локально й безкоштовно. Groq — швидко, але текст іде на чужий сервер</div>
            ${hnote("hlp-ai", "Ollama працює просто на вашому ПК — безкоштовно й приватно, текст нікуди не йде. Groq — це хмара: швидше й якісніше, але кожна диктовка вирушає на сервери Groq.")}</div>
          <div class="seg" role="group" aria-label="Режим полірування">
            <button data-llm="off" class="${s.llm === "off" ? "on" : ""}" aria-pressed="${s.llm === "off"}">Вимкнено</button>
            <button data-llm="ollama" class="${s.llm === "ollama" ? "on" : ""}" aria-pressed="${s.llm === "ollama"}">Ollama</button>
            <button data-llm="groq" class="${s.llm === "groq" ? "on" : ""}" aria-pressed="${s.llm === "groq"}">Groq</button></div></div>
        <div id="llmOllama" class="srow"><div style="min-width:0"><div class="lab">Модель Ollama</div>
            <div class="hint">Має бути завантажена: <span class="mono">ollama pull ${esc(s.ollamaModel || "qwen2.5:7b")}</span></div></div>
          <input class="inp mono" id="ollamaModel" value="${esc(s.ollamaModel || "")}" placeholder="qwen2.5:7b" aria-label="Модель Ollama"></div>
        <div id="llmGroq">
          <div class="srow"><div style="min-width:0"><div class="lab">Ключ Groq API</div>
              <div class="hint">Безкоштовний тариф на console.groq.com</div></div>
            <div class="key-wrap">
              <input class="inp mono" id="groqKey" type="password" value="${esc(s.groqKey || "")}" placeholder="gsk_…" aria-label="Ключ Groq API">
              <button class="mini" id="keyEye" aria-label="Показати ключ"></button></div></div>
          <div class="srow"><div style="min-width:0"><div class="lab">Модель Groq</div>
              <div class="hint">openai/gpt-oss-20b — швидка й безкоштовна. Список: console.groq.com/docs/models</div></div>
            <input class="inp mono" id="groqModel" value="${esc(s.groqModel || "")}" placeholder="openai/gpt-oss-20b" aria-label="Модель Groq"></div>
        </div>
        <div id="llmPromptBlock" style="padding-top:15px;border-top:1px solid var(--line)">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px;flex-wrap:wrap">
            <div><div class="lab">Інструкція для полірування</div>
              <div class="hint">Що саме AI робить з розпізнаним текстом. Порожнє — типова інструкція</div></div>
            <button class="btn ghost" id="llmPromptReset" style="padding:8px 13px;font-size:12px">Скинути до типового</button></div>
          <textarea class="ta mono" id="llmPrompt" rows="5" placeholder="Типова інструкція" aria-label="Інструкція для полірування">${esc(s.llmPrompt || s.llmPromptDefault || "")}</textarea>
        </div></div>`,
    license: `
      <div class="panel"><h2>Ліцензія</h2>
        <div class="desc">Ключ активується один раз і зберігається на цьому пристрої</div>
        ${licenseNoteHtml()}
        ${licenseGridHtml()}
        <div class="key-wrap" style="margin-top:16px">
          <input class="inp mono" id="licKey" placeholder="Вставте ключ ліцензії" aria-label="Ключ ліцензії">
          <button class="btn pri" id="licActivate">Активувати</button></div>
        <div class="note err" id="licError" style="margin-top:12px;display:none"></div></div>
      <div class="panel"><h2>Приватність</h2>
        <div class="note ${s.llm === "groq" ? "warn" : "ok"}" id="privacyNote"></div></div>
      <div class="panel"><h2>Знайомство</h2>
        <div class="srow" style="border:none;padding-bottom:0"><div style="min-width:0">
            <div class="lab">Пройти знайомство</div>
            <div class="hint">Показати вступний тур ще раз — крок за кроком. Не змінює ваших налаштувань.</div></div>
          <button class="btn ghost" id="obReplay">Пройти знайомство</button></div></div>`,
  };
  // recognition + polishing merged into one "AI" tab (shared Groq key)
  panes.model += panes.ai;
  el.innerHTML = `<h1 class="htitle">Налаштування</h1>
    <div class="stabs" role="tablist" aria-label="Налаштування">${STABS.map(([k, lab, ic]) =>
      `<button class="stab${tab === k ? " on" : ""}" role="tab" id="stab-${k}" aria-selected="${tab === k ? "true" : "false"}"
        aria-controls="stab-body" tabindex="${tab === k ? "0" : "-1"}" data-tab="${k}">${svg(ic, 16)}${lab}</button>`).join("")}</div>
    <div id="stab-body" role="tabpanel" aria-labelledby="stab-${tab}">${panes[tab]}</div>`;

  const tabs = [...el.querySelectorAll(".stab")];
  tabs.forEach((b) => {
    b.onclick = () => { state.settingsTab = b.dataset.tab; render(); focusTab(); };
    b.onkeydown = (e) => {
      const i = tabs.indexOf(b);
      let ni = -1;
      if (e.key === "ArrowRight") ni = (i + 1) % tabs.length;
      else if (e.key === "ArrowLeft") ni = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") ni = 0;
      else if (e.key === "End") ni = tabs.length - 1;
      if (ni < 0) return;
      e.preventDefault();
      state.settingsTab = tabs[ni].dataset.tab; render(); focusTab();
    };
  });

  // every toggle in every pane goes through the same save_settings payload
  el.querySelectorAll(".tg[data-key]").forEach((t) => t.onclick = () => {
    const k = t.dataset.key;
    s[k] = !s[k];
    t.classList.toggle("on", s[k]);
    t.setAttribute("aria-checked", s[k] ? "true" : "false");
    saveSettings();
  });

  if (tab === "general") {
    el.querySelector("#hotkeyBtn").onclick = captureHotkey;
    const cu = el.querySelector("#chkUpdBtn");
    if (cu) cu.onclick = (e) => checkUpdateManual(e.currentTarget);
  }
  if (tab === "floating") fpBind();
  if (tab === "mic") {
    const selMic = el.querySelector("#selMic");
    selMic.innerHTML = `<option value="">Системний за замовчуванням</option>` +
      state.devices.map((d) => `<option value="${esc(d.name)}">${esc(d.name)}</option>`).join("");
    selMic.value = s.inputDevice || "";
    selMic.onchange = () => { s.inputDevice = selMic.value; saveSettings(); };
    el.querySelector("#micTestBtn").onclick = (e) => toggleMicTest(e.currentTarget);
  }
  if (tab === "model") {
    renderModelList(el.querySelector("#mcards"));
    const selG = el.querySelector("#selGpu");
    selG.value = s.device || "cuda";
    selG.onchange = () => { s.device = selG.value; saveSettings(); };
    bindSttPane(el);
    bindAiPane(el);
  }
  if (tab === "license") {
    el.querySelector("#licActivate").onclick = async () => {
      const key = el.querySelector("#licKey").value.trim();
      const err = el.querySelector("#licError");
      if (!key) return;
      const res = await api("activate_license", key);
      if (res && res.ok) {
        state.license = { licensed: true, daysLeft: res.daysLeft, exp: res.exp,
                          reason: "ok", customer: res.customer || "" };
        render(); toast("Ліцензію активовано");
      } else {
        err.style.display = "flex";
        err.innerHTML = svg(ICON.warn, 15) + esc((res && res.error) || "Помилка активації");
      }
    };
    const rb = el.querySelector("#obReplay");
    if (rb) rb.onclick = () => openOnboarding();
    paintPrivacy();
  }
}
function focusTab() {
  const b = document.querySelector(`.stab[data-tab="${state.settingsTab}"]`);
  if (b) b.focus();
}
function licenseNoteHtml() {
  const l = state.license || {};
  if (l.licensed) {
    const soon = typeof l.daysLeft === "number" && l.daysLeft <= 7;
    return soon
      ? `<div class="note warn">${svg(ICON.warn, 15)}Спливає за ${l.daysLeft} дн. — продовжіть, щоб не втратити доступ</div>`
      : `<div class="note ok">${svg(ICON.shield, 15)}Активна · залишилось ${l.daysLeft} дн.</div>`;
  }
  return `<div class="note err">${svg(ICON.warn, 15)}${l.reason === "expired"
    ? `Ліцензію прострочено${l.exp ? " (" + esc(l.exp) + ")" : ""} — введіть новий ключ`
    : "Не активована — введіть ключ"}</div>`;
}
function licenseGridHtml() {
  const l = state.license || {};
  const rows = [
    ["Стан", l.licensed ? "Активна" : (l.reason === "expired" ? "Прострочена" : "Не активована")],
    ["Дійсна до", l.exp ? `<span class="mono">${esc(l.exp)}</span>` : "—"],
    ["Залишилось", typeof l.daysLeft === "number" ? `<span class="mono">${l.daysLeft}</span> дн.` : "—"],
    ["Покупець", l.customer ? esc(l.customer) : "—"],
    ["Пристрій", esc(state.gpu)],
  ];
  return `<div class="lic-grid">${rows.map(([k, v]) =>
    `<div class="lr"><span class="lk">${k}</span><span class="lv">${v}</span></div>`).join("")}</div>`;
}
function paintPrivacy() {
  const n = document.getElementById("privacyNote");
  if (!n) return;
  // the privacy claim has to follow reality: cloud STT sends the audio, cloud
  // polish sends the text; only fully-local dictation never leaves the device
  const sttCloud = state.settings.sttBackend === "cloud";
  const llmCloud = state.settings.llm === "groq";
  let msg, warn = true;
  if (sttCloud) {
    const prov = (STT_PROVIDERS[state.settings.sttProvider] || {}).label || "хмару";
    msg = `Хмарне розпізнавання: аудіо надсилається в ${prov}` + (llmCloud ? "; полірування — у Groq" : "");
  } else if (llmCloud) {
    msg = "Розпізнавання — локальне, але полірування надсилає текст у Groq";
  } else {
    msg = "Диктовки ніколи не залишають цей пристрій";
    warn = false;
  }
  n.innerHTML = svg(ICON.shield, 15) + msg;
  n.classList.toggle("warn", warn);
  n.classList.toggle("ok", !warn);
}
function bindAiPane(el) {
  const s = state.settings;
  const syncLlm = () => {
    el.querySelector("#llmOllama").style.display = s.llm === "ollama" ? "" : "none";
    el.querySelector("#llmGroq").style.display = s.llm === "groq" ? "" : "none";
    // the corrector instruction applies to both providers, so show it whenever
    // polishing is on at all
    el.querySelector("#llmPromptBlock").style.display = s.llm === "off" ? "none" : "";
    el.querySelectorAll(".seg [data-llm]").forEach((b) => {
      const on = b.dataset.llm === s.llm;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  };
  syncLlm();
  const setLlm = (v) => { s.llm = v; syncLlm(); saveSettings(); };
  el.querySelectorAll(".seg [data-llm]").forEach((b) => b.onclick = () => {
    const v = b.dataset.llm;
    if (v === s.llm) return;
    // Groq is the one switch that sends dictated text off this device: gate it
    // behind an explicit confirmation instead of flipping it silently
    if (v === "groq") {
      confirmModal({
        title: "Надсилати текст у Groq?",
        body: "Полірування через Groq відправлятиме розшифрований текст кожної диктовки на сервери Groq. Не вмикайте це для конфіденційних даних. Розпізнавання голосу лишиться на цьому пристрої.",
        confirmLabel: "Так, надсилати в Groq",
        onConfirm: () => setLlm("groq"),
      });
      return;
    }
    setLlm(v);
  });
  const bindText = (id, key) => {
    const inp = el.querySelector("#" + id);
    inp.onchange = () => { s[key] = inp.value.trim(); saveSettings(); };
  };
  bindText("ollamaModel", "ollamaModel");
  bindText("groqModel", "groqModel");
  bindText("groqKey", "groqKey");
  const promptArea = el.querySelector("#llmPrompt");
  promptArea.onchange = () => { s.llmPrompt = promptArea.value; saveSettings(); };
  el.querySelector("#llmPromptReset").onclick = () => {
    promptArea.value = s.llmPromptDefault || "";
    s.llmPrompt = "";  // stored blank -> app uses the built-in default
    saveSettings();
    toast("Інструкцію скинуто до типової");
  };
  const eye = el.querySelector("#keyEye");
  setEye(eye);
  eye.onclick = () => {
    s.groqKeyVisible = !s.groqKeyVisible;
    el.querySelector("#groqKey").type = s.groqKeyVisible ? "text" : "password";
    setEye(eye);
  };
}
function setEye(btn) {
  btn.innerHTML = svg(state.settings.groqKeyVisible ? ICON.eyeOff : ICON.eye, 15);
  btn.setAttribute("aria-label", state.settings.groqKeyVisible ? "Сховати ключ" : "Показати ключ");
  btn.setAttribute("aria-pressed", state.settings.groqKeyVisible ? "true" : "false");
}
function saveSettings() {
  // one payload, one Python method: save_settings(s) in webview_app.py reads the
  // camelCase keys it knows and ignores the rest, so every control on every tab
  // — including the floating-panel ones — travels through this single call.
  const p = api("save_settings", JSON.parse(JSON.stringify(state.settings)));
  paintPrivacy();
  return p;
}
let saveTimer = null;
// the drag and the range slider fire continuously; coalesce them into one write
function saveSettingsSoon() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveSettings, 350);
}

// ---- model library ----
function fmtMb(mb) { return mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : mb + " MB"; }
function bindSttCloud(el) {
  // (re)bind the controls inside #sttCloud; called on first render and after the
  // provider changes (which re-renders the block's inner HTML)
  const prov = el.querySelector("#sttProvider");
  if (prov) prov.onchange = () => {
    state.settings.sttProvider = prov.value;
    // reset the model to the new provider's first option
    state.settings.sttModel = sttProvider().models[0].id;
    const cloud = el.querySelector("#sttCloud");
    if (cloud) { cloud.innerHTML = sttCloudHtml(); bindSttCloud(el); }
    const act = el.querySelector("#sttActive");
    if (act) act.innerHTML = sttActiveLabel();
    saveSettingsSoon();
  };
  const mdl = el.querySelector("#sttModel");
  if (mdl) mdl.onchange = () => {
    state.settings.sttModel = mdl.value;
    const b = el.querySelector("#sttBadges");
    if (b) b.innerHTML = sttModelBadgesHtml();
    const act = el.querySelector("#sttActive");
    if (act) act.innerHTML = sttActiveLabel();
    saveSettingsSoon();
  };
  const p = sttProvider();
  if (!p.reuseGroqKey && p.keyProp) {
    const key = el.querySelector("#" + p.keyProp);
    if (key) key.oninput = () => { state.settings[p.keyProp] = key.value; saveSettingsSoon(); };
  }
  const vb = el.querySelector("#sttVerify");
  if (vb) vb.onclick = async () => {
    const note = el.querySelector("#sttVerifyNote");
    const lbl = vb.textContent;
    vb.disabled = true; vb.textContent = "Перевіряю…";
    try {
      await saveSettings();                 // persist provider/model/key first
      const r = await api("verify_stt");
      if (note) {
        note.style.display = "flex";
        note.className = "note " + (r && r.ok ? "ok" : "err");
        note.innerHTML = svg(r && r.ok ? ICON.check : ICON.warn, 15) +
          esc((r && r.message) || "Немає відповіді");
      }
    } finally {
      vb.disabled = false; vb.textContent = lbl;
    }
  };
}
function bindSttPane(el) {
  const cards = [...el.querySelectorAll("#sttModes [data-stt]")];
  cards.forEach((b) => {
    b.onclick = () => {
      const v = b.dataset.stt;
      state.settings.sttBackend = v;
      cards.forEach((x) => {
        const on = x === b;
        x.classList.toggle("on", on);
        x.setAttribute("aria-checked", on ? "true" : "false");
      });
      const local = el.querySelector("#sttLocal"), cloud = el.querySelector("#sttCloud");
      if (local) local.toggleAttribute("hidden", v !== "local");
      if (cloud) cloud.toggleAttribute("hidden", v !== "cloud");
      saveSettings();
    };
  });
  bindSttCloud(el);
}
function renderModelList(host) {
  if (!host) return;
  const activeIdx = state.models.findIndex((m) => m.active);
  const focusIdx = activeIdx >= 0 ? activeIdx : 0;
  host.innerHTML = state.models.map((m, i) => {
    // downloaded models report real disk use, which runs above the download
    // size because the HF cache keeps blobs and snapshot copies side by side
    const meta = m.installed ? `на диску · ${fmtMb(m.diskMb)}` : `завантаження · ${esc(m.size)}`;
    const tags = [m.en ? "тільки англійська" : "", m.note].filter(Boolean).map(esc).join(" · ");
    let bottom = "";
    if (m.installed && !m.active) bottom = `<button class="mdel" data-act="del" data-id="${esc(m.id)}">${svg(ICON.trash, 12)}Видалити з диска</button>`;
    else if (!m.installed) bottom = `<div class="dl">↓ Завантажити</div>`;
    const status = m.active ? "Активна" : (m.installed ? "на диску" : "не завантажена");
    return `<div class="mcard${m.active ? " on" : ""}" role="radio" aria-checked="${m.active ? "true" : "false"}"
      aria-label="${esc(m.label)} — ${status}" tabindex="${i === focusIdx ? 0 : -1}" data-mid="${esc(m.id)}">
      <div class="chk">${svg(ICON.check, 12)}</div>
      <div class="lab">${esc(m.label)}</div>
      <div class="hint">${meta}${tags ? " — " + tags : ""}</div>
      ${bottom}</div>`;
  }).join("");

  const cards = [...host.querySelectorAll(".mcard")];
  const activate = async (id) => {
    const m = state.models.find((x) => x.id === id);
    if (!m) return;
    if (m.installed) {
      const r = await api("activate_model", id);
      if (r && r.ok === false) return toast(r.error || "не вдалося");
    } else {
      const card = host.querySelector(`.mcard[data-mid="${id}"]`);
      if (card) {
        card.querySelector(".dl, .dlwrap, .mdel")?.remove();
        card.insertAdjacentHTML("beforeend",
          `<div class="dlwrap"><div class="dlbar"><span></span></div><div class="dltx">Качається…</div></div>`);
      }
      const r = await api("download_model", id);
      if (r && r.ok === false) { toast(r.error || "не вдалося"); await refreshModels(host); return; }
      pollModelDownload(host);
      return;  // list refreshes when the download finishes
    }
    await refreshModels(host);
    const again = host.querySelector(`.mcard[data-mid="${id}"]`);
    if (again) { again.tabIndex = 0; again.focus(); }
  };
  cards.forEach((c) => {
    c.onclick = (e) => {
      if (e.target.closest("[data-act='del']")) return;
      activate(c.dataset.mid);
    };
    c.onkeydown = (e) => {
      const idx = cards.indexOf(c);
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") { e.preventDefault(); activate(c.dataset.mid); return; }
      let ni = -1;
      if (e.key === "ArrowDown" || e.key === "ArrowRight") ni = (idx + 1) % cards.length;
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") ni = (idx - 1 + cards.length) % cards.length;
      if (ni < 0) return;
      e.preventDefault();
      cards.forEach((x) => x.tabIndex = -1);
      cards[ni].tabIndex = 0; cards[ni].focus();
    };
  });
  host.querySelectorAll("[data-act='del']").forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    const id = b.dataset.id, m = state.models.find((x) => x.id === id);
    confirmModal({
      title: `Видалити ${m ? m.label : "модель"}?`,
      body: `Файли моделі буде прибрано з диска${m && m.diskMb ? `. Звільниться ${fmtMb(m.diskMb)}` : ""}. Її можна завантажити знову будь-коли.`,
      confirmLabel: "Видалити",
      onConfirm: async () => {
        const r = await api("delete_model", id);
        if (r && r.ok === false) return toast(r.error || "не вдалося");
        await refreshModels(host);
      },
    });
  });
}
async function refreshModels(host) {
  state.models = (await api("list_models")) || state.models;
  const active = state.models.find((m) => m.active);
  if (active) state.settings.model = active.id;
  renderModelList(host || document.getElementById("mcards"));
}
// distinct from pollDownload() (the Home hero banner): this one tracks a model
// download started from the Models list and refreshes that list when it ends
let modelDlTimer = null;
function pollModelDownload(host) {
  if (modelDlTimer) return;
  modelDlTimer = setInterval(async () => {
    const d = await api("get_download");
    const el = document.getElementById("mcards");
    if (!el) { clearInterval(modelDlTimer); modelDlTimer = null; return; }
    // finish only when the backend says it's no longer downloading; `active`
    // alone lags at the start (cache walk) and would end the poll prematurely
    if (d && d.downloading) {
      const bar = el.querySelector(".dlwrap .dlbar span");
      const tx = el.querySelector(".dlwrap .dltx");
      if (bar && d.pct != null) bar.style.transform = `scaleX(${(Math.max(0, Math.min(100, d.pct)) / 100).toFixed(3)})`;
      if (tx) tx.textContent = d.pct != null ? `Завантаження… ${Math.round(d.pct)}%`
        : (d.mb ? `Качається… ${fmtMb(d.mb)}` : "Качається…");
    } else {
      clearInterval(modelDlTimer); modelDlTimer = null;
      if (d && d.error) toast("Не вдалося завантажити модель: " + d.error);
      await refreshModels(host);
    }
  }, 700);
}

// ---- mic test / level meter ----
let micTestTimer = null;
function stopMicTest() {
  if (!micTestTimer) return;
  clearInterval(micTestTimer); micTestTimer = null;
  api("mic_test", false);
}
let micTestPeak = 0;
async function toggleMicTest(btn) {
  if (micTestTimer) {
    stopMicTest();
    btn.textContent = "Перевірити"; btn.classList.remove("pri"); btn.classList.add("ghost");
    const f = document.getElementById("levelFill"); if (f) f.style.transform = "scaleX(0)";
    const hint = document.getElementById("micHint"); if (hint) hint.textContent = "";
    return;
  }
  await api("mic_test", true);
  btn.textContent = "Стоп"; btn.classList.remove("ghost"); btn.classList.add("pri");
  micTestPeak = 0;
  micTestTimer = setInterval(async () => {
    const lvl = await api("get_input_level");
    micTestPeak = Math.max(micTestPeak, lvl);
    const f = document.getElementById("levelFill");
    // scaleX, not width: this repaints ~10x/s while Whisper is on the GPU, and a
    // transform stays on the compositor instead of forcing a layout every frame.
    // Full scale is 0.1 RMS, which puts the .level .th tick (20%) exactly on the
    // 0.02 "the mic hears you" threshold used below.
    if (f) {
      f.style.transform = `scaleX(${Math.min(1, lvl / 0.1)})`;
      f.style.background = lvl > 0.02 ? "var(--aqua)" : "var(--coral)";
    }
    const hint = document.getElementById("micHint");
    if (hint) hint.textContent = micTestPeak > 0.02
      ? "Мікрофон чує голос ✓"
      : "Говоріть у мікрофон… Якщо смужка майже не рухається — підніміть гучність мікрофона у Windows (Звук → Ввід → Властивості → Рівні).";
  }, 100);
}

// ---- hotkey capture ----
async function captureHotkey() {
  const btn = document.getElementById("hotkeyBtn");
  const cap = document.getElementById("hkCap");
  btn.classList.remove("ghost"); btn.classList.add("pri");
  btn.textContent = "Слухаю…";
  const combo = await api("capture_hotkey");
  state.hotkey = combo || state.hotkey;
  btn.classList.remove("pri"); btn.classList.add("ghost");
  btn.textContent = "Змінити";
  if (cap) cap.textContent = state.hotkey;
  paintTopHint();
}

// ================= FLOATING PANEL (Settings → Панель) =================
// One placement truth: percentages of the FREE space inside the screen
// (0 = flush to the start edge, 50 = centred, 100 = flush to the end edge).
// The nine presets are simply the points where both axes land on 0 / 50 / 100 —
// the same model flow.py documents for overlay_position, so a preset is stored
// as its string ("bottom-center") and anything else as {x, y}.
const FP_POS = [["top-left", "t", "l", "Вгорі ліворуч"], ["top-center", "t", "c", "Вгорі по центру"], ["top-right", "t", "r", "Вгорі праворуч"],
                ["middle-left", "m", "l", "Посередині ліворуч"], ["center", "m", "c", "По центру"], ["middle-right", "m", "r", "Посередині праворуч"],
                ["bottom-left", "b", "l", "Внизу ліворуч"], ["bottom-center", "b", "c", "Внизу по центру"], ["bottom-right", "b", "r", "Внизу праворуч"]];
const FP_VY = { t: 0, m: 50, b: 100 }, FP_HX = { l: 0, c: 50, r: 100 };
const FP_ANCH = [0, 50, 100];
const FP_STYLES = [
  { id: "pill", label: "Пігулка", hint: "Крапка, рівень і таймер — найменша капсула", ready: true },
  { id: "orb", label: "Кільце", hint: "Кругле — саме кільце показує стан і рівень", ready: true },
  { id: "dock", label: "Док", hint: "Ширша смуга: крапка, хвиля й таймер (лише показ)", ready: true },
];
const FP_GLYPH = {
  pill: `<svg width="56" height="20" viewBox="0 0 56 20" fill="none" aria-hidden="true" focusable="false">
    <rect class="g-n" x="1" y="1" width="54" height="18" rx="9" stroke-width="1.6"/>
    <circle class="g-cf" cx="10" cy="10" r="3"/>
    <g class="g-cf"><rect x="17" y="6.5" width="2" height="7" rx="1"/><rect x="21" y="4" width="2" height="12" rx="1"/><rect x="25" y="7" width="2" height="6" rx="1"/></g>
    <rect class="g-nf" x="32" y="7.5" width="15" height="5" rx="2.5"/></svg>`,
  orb: `<svg width="30" height="30" viewBox="0 0 30 30" fill="none" aria-hidden="true" focusable="false">
    <circle class="g-n" cx="15" cy="15" r="13" stroke-width="1.6" opacity=".5"/>
    <path class="g-c" d="M15 2a13 13 0 0 1 11.3 19.5" stroke-width="2.8" stroke-linecap="round"/>
    <circle class="g-cf" cx="15" cy="15" r="3.4"/></svg>`,
  dock: `<svg width="64" height="22" viewBox="0 0 64 22" fill="none" aria-hidden="true" focusable="false">
    <rect class="g-n" x="1" y="1" width="62" height="20" rx="6" stroke-width="1.6"/>
    <circle class="g-cf" cx="8.5" cy="11" r="2.6"/>
    <g class="g-cf"><rect x="14" y="8" width="1.8" height="6" rx=".9"/><rect x="17.6" y="5.5" width="1.8" height="11" rx=".9"/><rect x="21.2" y="7.5" width="1.8" height="7" rx=".9"/><rect x="24.8" y="4.5" width="1.8" height="13" rx=".9"/><rect x="28.4" y="8" width="1.8" height="6" rx=".9"/></g>
    <rect class="g-nf" x="34" y="8.5" width="10" height="5" rx="2.5"/>
    <rect class="g-n" x="47" y="5" width="6.5" height="12" rx="3.2" stroke-width="1.4"/>
    <rect class="g-cf" x="55.5" y="5" width="6.5" height="12" rx="3.2"/></svg>`,
};
// The ported pill is authored in em and sized by font-size, not by transform:
// it measures ~4.26em wide, so 4.18cqw / em lands it on ~17.8% of the mock screen
// at 100% and ~24.9% at 140% — the honest share a 40px pill has on a real 1920px
// display. No px minimums anywhere, or the preview would lie at small widths.
const FP_PILL_CQ = 4.18;
const fpPosMeta = (p) => FP_POS.find((x) => x[0] === p) || FP_POS[7];
const fpPresetAt = (x, y) => { const e = FP_POS.find(([, v, h]) => FP_HX[h] === x && FP_VY[v] === y); return e ? e[0] : null; };
const fpNearestPreset = (x, y) => {
  const near = (v) => FP_ANCH.reduce((a, b) => Math.abs(b - v) < Math.abs(a - v) ? b : a);
  return fpPresetAt(near(x), near(y));
};
function fpXY() {
  const p = state.settings.overlayPosition;
  if (p && typeof p === "object" && typeof p.x === "number" && typeof p.y === "number") {
    return { x: Math.max(0, Math.min(100, Math.round(p.x))), y: Math.max(0, Math.min(100, Math.round(p.y))) };
  }
  const m = fpPosMeta(typeof p === "string" ? p : "bottom-center");
  return { x: FP_HX[m[2]], y: FP_VY[m[1]] };
}
const fpScale = () => Math.max(80, Math.min(140, +state.settings.overlayScale || 100));
const fpOpacity = () => Math.max(40, Math.min(100, +state.settings.overlayOpacity || 82));
function fpPlaceStyle() {
  // left:x% + translate(-x%) + transform-origin:x% puts the widget's own x% point
  // on the screen's x% point, i.e. its visual left edge lands at x% of the free
  // space. That keeps it inside the display for any x,y in 0..100, at any scale.
  const { x, y } = fpXY(), sc = fpScale() / 100;
  return `left:${x}%;top:${y}%;transform:translate(${-x}%,${-y}%);transform-origin:${x}% ${y}%;`
    + `--fpsc:1;--fp-op:${fpOpacity()};font-size:${(FP_PILL_CQ * sc).toFixed(3)}cqw`;
}
function fpPosText() {
  const { x, y } = fpXY(), p = fpPresetAt(x, y);
  return p ? fpPosMeta(p)[3] : `Власне розташування · X ${x} % · Y ${y} %`;
}
function fpStyleLabel(id) { const s = FP_STYLES.find((x) => x.id === id); return s ? s.label : id; }
function floatingPanel() {
  const s = state.settings, off = !s.floatingPanel;
  const { x, y } = fpXY();
  const sel = fpPresetAt(x, y), near = sel || fpNearestPreset(x, y);
  const styles = FP_STYLES.map((st) => {
    const on = s.overlayStyle === st.id;
    return `<div class="fp-style${on ? " on" : ""}" role="radio" aria-checked="${on ? "true" : "false"}"
      aria-label="${esc(st.label + " — " + st.hint)}" tabindex="0" data-fps="${st.id}">
      <div class="chk">${svg(ICON.check, 11)}</div>
      <div class="gl" aria-hidden="true">${FP_GLYPH[st.id]}</div>
      <div class="lab">${st.label}</div>
      <div class="hint">${st.hint}</div></div>`;
  }).join("");
  const cells = FP_POS.map(([p, v, h, lab]) => {
    const on = sel === p;
    return `<button type="button" class="fp-cell${on ? " on" : ""}${!sel && near === p ? " near" : ""}" role="radio"
      aria-checked="${on ? "true" : "false"}" aria-label="${esc(lab)}" tabindex="${near === p ? 0 : -1}"
      data-fpp="${p}" data-v="${v}" data-h="${h}"><i aria-hidden="true"></i></button>`;
  }).join("");
  return `<div class="panel"><h2>Плаваюча панель</h2>
    <div class="desc">Маленький індикатор запису, який лежить поверх усіх вікон, поки ви диктуєте</div>
    <div class="srow" style="padding-top:0"><div style="min-width:0">
        <div class="lab">Показувати панель</div><div class="hint">Індикатор запису поверх усіх вікон</div></div>
      <button class="tg ${s.floatingPanel ? "on" : ""}" role="switch" aria-checked="${s.floatingPanel ? "true" : "false"}"
        aria-label="Показувати плаваючу панель" aria-controls="fpBody" id="fpMaster"><span class="th"></span></button></div>
    <div class="helpnote" id="fpOff" style="margin-top:2px;max-width:none"${off ? "" : " hidden"}>Плаваючу панель вимкнено — під час диктування на екрані нічого не зʼявляється. Увімкніть її, щоб обрати вигляд, розташування й розмір.</div>
    <div id="fpBody"${off ? " hidden" : ""}>
      <div class="fp-layout">
        <div class="fp-ctrls">
          <div class="fp-field">
            <div class="fp-flab" id="fpStyleLab">Вигляд</div>
            <div class="fp-fhint">Який вигляд має індикатор під час запису. Док — лише показ (крапка, хвиля, таймер): вікно панелі прозоре для кліків, тож кнопок на ньому бути не може.</div>
            <div class="fp-styles" id="fpStyles" role="radiogroup" aria-labelledby="fpStyleLab">${styles}</div>
          </div>
          <div class="fp-field">
            <div class="fp-flab" id="fpPosLab">Розташування</div>
            <div class="fp-fhint">Швидкі пресети — або перетягніть панель просто на прев'ю</div>
            <div class="fp-pos" id="fpPos" role="radiogroup" aria-labelledby="fpPosLab">${cells}</div>
            <div class="fp-fhint" style="margin-top:9px">Перетягніть панель по екрану або оберіть клітинку. Стрілки — крок 2 %, Shift + стрілки — 10 %, Enter — до найближчої клітинки, Home — вниз по центру, End — по центру екрана.</div>
          </div>
          <div class="fp-field">
            <div class="fp-flab"><label for="fpSize">Розмір</label></div>
            <div class="fp-fhint">Масштаб панелі — від 80 % до 140 %</div>
            <div class="fp-sizerow">
              <input type="range" class="fp-range" id="fpSize" min="80" max="140" step="5"
                value="${fpScale()}" aria-valuetext="${fpScale()}%">
              <output class="fp-sizeval" id="fpSizeVal" for="fpSize">${fpScale()}%</output>
            </div>
          </div>
          <div class="fp-field">
            <div class="fp-flab"><label for="fpOpacity">Прозорість</label></div>
            <div class="fp-fhint">Наскільки крізь панель видно вікна під нею — від 40 % до 100 % (суцільна). Текст і крапка лишаються чіткими.</div>
            <div class="fp-sizerow">
              <input type="range" class="fp-range" id="fpOpacity" min="40" max="100" step="2"
                value="${fpOpacity()}" aria-valuetext="${fpOpacity()}%">
              <output class="fp-sizeval" id="fpOpacityVal" for="fpOpacity">${fpOpacity()}%</output>
            </div>
          </div>
        </div>
        <div class="fp-prevwrap" role="group" aria-label="Живий прев'ю">
          <div class="fp-flab">Живий прев'ю</div>
          <div class="fp-fhint">Так панель виглядатиме на вашому екрані під час запису — перетягніть її, куди зручно</div>
          <div class="fp-screen">
            <div class="fp-desk" aria-hidden="true"><div class="bar"></div><div class="win"></div></div>
            <div class="fp-inset" id="fpStage"></div>
          </div>
          <div class="fp-cap" id="fpCap" role="status" aria-live="polite"></div>
        </div>
      </div>
    </div></div>`;
}
const fpBars = (n) => Array.from({ length: n }, (_, i) =>
  `<i style="animation-delay:${(-i * 0.11).toFixed(2)}s;animation-duration:${(1 + ((i * 7) % 5) * 0.14).toFixed(2)}s"></i>`).join("");
function fpWidgetMarkup() {
  // the recording-state mini render of whichever shape is chosen, authored in em
  // off the same font-size, so all three keep their honest share of the mock
  // screen (the pill/dock wave sheds bars the way an icon sheds detail at 16px).
  const style = state.settings.overlayStyle;
  if (style === "orb") {
    // the ring itself is the UI: a coral arc that rides the level, timer inside
    return `<div class="fpw-orb" data-state="rec">
      <svg class="po-ring" viewBox="0 0 68 68" aria-hidden="true" focusable="false">
        <circle class="po-trk" cx="34" cy="34" r="28"/>
        <circle class="po-arc" cx="34" cy="34" r="28"/></svg>
      <span class="po-tm">0:07</span></div>`;
  }
  if (style === "dock") {
    // DISPLAY-ONLY wide bar: dot + wave + timer. No buttons — the real overlay
    // window is click-through (WS_EX_TRANSPARENT) and could never receive one.
    return `<div class="fpw-dock" data-state="rec">
      <span class="pd-dot"></span>
      <span class="pd-bars">${fpBars(9)}</span>
      <span class="pd-tm">0:07</span></div>`;
  }
  // the real pill, ported from the shipping tray build: one coral identity, state
  // carried by the dot's geometry, a tabular-mono timer — and a FIVE-bar wave. The
  // window draws 13; at preview scale 13 bars land sub-pixel and smear into one
  // coral blur, so the lane sheds detail the way an icon does at 16px. The pill's
  // outer width, and therefore the honest proportion, is unchanged.
  return `<div class="fpw-pill" data-state="rec">
    <span class="pp-row">
      <span class="pp-dot"><span class="pp-halo"></span>
        <svg class="pp-glyph" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <circle class="pp-ring" cx="8" cy="8"/>
          <circle class="pp-arc" cx="8" cy="8" r="5"/>
          <path class="pp-check" d="M5.1 8.2 7.1 10.2 11 6.1"/>
          <path class="pp-strike" d="M4.3 11.7 11.7 4.3"/>
        </svg></span>
      <span class="pp-bars">${fpBars(5)}</span>
      <span class="pp-lab">Готовий</span>
      <span class="pp-key">${esc(state.hotkey)}</span>
      <span class="pp-tm">0:07</span>
    </span></div>`;
}
function fpWidgetLabel() {
  return `Плаваюча панель, ${fpPosText()}. Перетягніть мишею або посуньте стрілками; Enter — до найближчої клітинки, Home — вниз по центру`;
}
function fpCaption() {
  const cap = document.getElementById("fpCap");
  if (!cap) return;
  cap.innerHTML = `<b>${esc(fpStyleLabel(state.settings.overlayStyle))}</b> · <b>${esc(fpPosText())}</b> · <b>${fpScale()}</b> % · прозорість <b>${fpOpacity()}</b> %`;
}
function fpPaint() {
  const stage = document.getElementById("fpStage");
  if (!stage) return;
  stage.innerHTML = `<i class="fp-guide gx" aria-hidden="true"></i><i class="fp-guide gy" aria-hidden="true"></i>
    <button type="button" class="fp-w" id="fpW" style="${fpPlaceStyle()}" aria-label="${esc(fpWidgetLabel())}">${fpWidgetMarkup()}</button>`;
  const w = stage.querySelector("#fpW");
  w.addEventListener("pointerdown", fpDragStart);
  w.addEventListener("pointermove", fpDragMove);
  w.addEventListener("pointerup", fpDragEnd);
  w.addEventListener("pointercancel", fpDragEnd);
  w.addEventListener("keydown", fpWidgetKey);
  w.addEventListener("click", fpWidgetClick);
  fpSyncCells();
  fpCaption();
}
// the 3x3 and the free coordinate must never contradict each other: a cell is
// selected only when the placement really is that preset; otherwise the nearest
// cell is hinted, not checked.
function fpSyncCells() {
  const { x, y } = fpXY(), sel = fpPresetAt(x, y), near = sel || fpNearestPreset(x, y);
  document.querySelectorAll("#fpPos .fp-cell").forEach((c) => {
    const on = c.dataset.fpp === sel;
    c.classList.toggle("on", on);
    c.classList.toggle("near", !sel && c.dataset.fpp === near);
    c.setAttribute("aria-checked", on ? "true" : "false");
    c.tabIndex = (c.dataset.fpp === near) ? 0 : -1;
  });
}
function fpApplyXY(x, y, save = true) {
  const preset = fpPresetAt(x, y);
  // store a preset as its name and a free point as {x, y} — the two shapes
  // flow.py's overlay_position already accepts
  state.settings.overlayPosition = preset || { x, y };
  const w = document.getElementById("fpW");
  if (w) { w.setAttribute("style", fpPlaceStyle()); w.setAttribute("aria-label", fpWidgetLabel()); }
  fpSyncCells(); fpCaption();
  if (save) saveSettingsSoon();
}
function fpBind() {
  const master = document.getElementById("fpMaster");
  if (master) master.onclick = () => {
    const on = !state.settings.floatingPanel;
    state.settings.floatingPanel = on;
    master.classList.toggle("on", on);
    master.setAttribute("aria-checked", on ? "true" : "false");
    const body = document.getElementById("fpBody"), offn = document.getElementById("fpOff");
    if (body) body.toggleAttribute("hidden", !on);
    if (offn) offn.toggleAttribute("hidden", on);
    if (on) fpPaint();
    saveSettings();
  };
  const styles = [...document.querySelectorAll("#fpStyles .fp-style[data-fps]")];
  styles.forEach((c) => {
    const pick = () => {
      state.settings.overlayStyle = c.dataset.fps;
      styles.forEach((x) => {
        const on = x === c;
        x.classList.toggle("on", on);
        x.setAttribute("aria-checked", on ? "true" : "false");
      });
      fpPaint(); saveSettings();
    };
    c.onclick = pick;
    c.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") { e.preventDefault(); pick(); }
    };
  });
  const cells = [...document.querySelectorAll("#fpPos .fp-cell")];
  cells.forEach((c) => {
    c.onclick = () => {
      const m = fpPosMeta(c.dataset.fpp);
      fpApplyXY(FP_HX[m[2]], FP_VY[m[1]]);
      const on = document.querySelector("#fpPos .fp-cell.on");
      if (on) on.focus();
    };
    c.onkeydown = (e) => {
      const idx = cells.indexOf(c);
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") { e.preventDefault(); c.click(); return; }
      let ni = -1;
      if (e.key === "ArrowRight") ni = (idx + 1) % 9;
      else if (e.key === "ArrowLeft") ni = (idx + 8) % 9;
      else if (e.key === "ArrowDown") ni = (idx + 3) % 9;
      else if (e.key === "ArrowUp") ni = (idx + 6) % 9;
      else if (e.key === "Home") ni = 0;
      else if (e.key === "End") ni = 8;
      if (ni < 0) return;
      e.preventDefault();
      cells.forEach((x) => x.tabIndex = -1);
      cells[ni].tabIndex = 0; cells[ni].focus();
    };
  });
  const size = document.getElementById("fpSize");
  if (size) size.oninput = () => {
    const v = Math.max(80, Math.min(140, +size.value || 100));
    state.settings.overlayScale = v;
    size.setAttribute("aria-valuetext", v + "%");
    const out = document.getElementById("fpSizeVal");
    if (out) out.textContent = v + "%";
    const w = document.getElementById("fpW");
    if (w) w.setAttribute("style", fpPlaceStyle());
    fpCaption();
    saveSettingsSoon();
  };
  const op = document.getElementById("fpOpacity");
  if (op) op.oninput = () => {
    const v = Math.max(40, Math.min(100, +op.value || 82));
    state.settings.overlayOpacity = v;
    op.setAttribute("aria-valuetext", v + "%");
    const out = document.getElementById("fpOpacityVal");
    if (out) out.textContent = v + "%";
    const w = document.getElementById("fpW");
    if (w) w.style.setProperty("--fp-op", v);
    fpCaption();
    saveSettingsSoon();
  };
  if (state.settings.floatingPanel) fpPaint();
}
// ---- free placement: pointer drag with releasable magnets ----
const FP_SNAP = 8;  // magnet threshold, in points of the 0..100 free-space scale
let fpDrag = null;
const fpSnap = (v) => {
  for (const a of FP_ANCH) if (Math.abs(v - a) <= FP_SNAP) return { v: a, hit: true };
  return { v: Math.round(v), hit: false };
};
function fpGuides(gx, gy) {
  const vx = document.querySelector("#fpStage .gx"), vy = document.querySelector("#fpStage .gy");
  if (vx) { vx.classList.toggle("on", gx !== null); if (gx !== null) vx.style.cssText = `left:${gx}%;transform:translateX(-${gx}%)`; }
  if (vy) { vy.classList.toggle("on", gy !== null); if (gy !== null) vy.style.cssText = `top:${gy}%;transform:translateY(-${gy}%)`; }
}
function fpDragStart(e) {
  if (e.pointerType === "mouse" && e.button !== 0) return;
  const w = e.currentTarget, area = document.getElementById("fpStage");
  if (!area) return;
  const ab = area.getBoundingClientRect(), wb = w.getBoundingClientRect();
  if (ab.width - wb.width <= 0 && ab.height - wb.height <= 0) return;
  fpDrag = { id: e.pointerId, ab, ww: wb.width, wh: wb.height, gx: e.clientX - wb.left, gy: e.clientY - wb.top, moved: false };
  try { w.setPointerCapture(e.pointerId); } catch (_) { /* no capture: plain mouse move still works */ }
  w.classList.add("drag");
  // dragging is a pointer gesture; silence the live region until the drop
  const cap = document.getElementById("fpCap");
  if (cap) cap.setAttribute("aria-live", "off");
  e.preventDefault();
}
function fpDragMove(e) {
  if (!fpDrag || e.pointerId !== fpDrag.id) return;
  const d = fpDrag, fw = d.ab.width - d.ww, fh = d.ab.height - d.wh;
  const raw = (px, free) => free > 0 ? Math.max(0, Math.min(100, (px / free) * 100)) : 50;
  const sx = fpSnap(raw(e.clientX - d.ab.left - d.gx, fw)), sy = fpSnap(raw(e.clientY - d.ab.top - d.gy, fh));
  d.moved = true;
  fpGuides(sx.hit ? sx.v : null, sy.hit ? sy.v : null);
  fpApplyXY(sx.v, sy.v, false);   // one write on drop instead of one per frame
}
function fpDragEnd(e) {
  if (!fpDrag || e.pointerId !== fpDrag.id) return;
  fpDrag = null;
  const w = e.currentTarget;
  try { w.releasePointerCapture(e.pointerId); } catch (_) { /* already released */ }
  w.classList.remove("drag");
  fpGuides(null, null);
  const cap = document.getElementById("fpCap");
  if (cap) { cap.setAttribute("aria-live", "polite"); fpCaption(); }
  saveSettings();
}
// Enter / Space on the widget aligns it to the nearest preset — a real action for
// a real button (e.detail === 0 means the click came from the keyboard)
function fpWidgetClick(e) {
  if (e.detail !== 0) return;
  const { x, y } = fpXY(), m = fpPosMeta(fpNearestPreset(x, y));
  fpApplyXY(FP_HX[m[2]], FP_VY[m[1]]);
}
function fpWidgetKey(e) {
  const step = e.shiftKey ? 10 : 2;
  let { x, y } = fpXY(), act = true;
  if (e.key === "ArrowLeft") x -= step;
  else if (e.key === "ArrowRight") x += step;
  else if (e.key === "ArrowUp") y -= step;
  else if (e.key === "ArrowDown") y += step;
  else if (e.key === "Home") { x = 50; y = 100; }
  else if (e.key === "End") { x = 50; y = 50; }
  else act = false;
  if (!act) return;
  e.preventDefault();
  fpApplyXY(Math.max(0, Math.min(100, Math.round(x))), Math.max(0, Math.min(100, Math.round(y))));
}

// ================= FIRST-RUN ONBOARDING =================
// A full-surface wizard shown once on a brand-new install (bootstrap
// onboarded:false) and re-openable from Settings → Ліцензія. Every step drives
// the SAME bridge method its matching settings control uses; leaving happens
// only by finishing the last step or an explicit Skip, both of which persist the
// gate through api("finish_onboarding") and drop the user on Home.
const OB_STEPS = ["welcome", "lang", "model", "mic", "hotkey", "license", "done"];
const OB_LABEL = { welcome: "Вітаємо", lang: "Мова", model: "Модель", mic: "Мікрофон",
                   hotkey: "Клавіша", license: "Ліцензія", done: "Готово" };
const OB_BRANDMARK = `<svg class="brandmark" width="34" height="34" viewBox="0 0 100 100" fill="none" aria-hidden="true"><g><line x1="50.00" y1="21.00" x2="50.00" y2="10.50" stroke="#33CBBB" stroke-width="2.3" stroke-linecap="round"/><line x1="54.54" y1="21.36" x2="56.18" y2="10.99" stroke="#34CABA" stroke-width="2.3" stroke-linecap="round"/><line x1="58.96" y1="22.42" x2="62.21" y2="12.43" stroke="#38C9B9" stroke-width="2.3" stroke-linecap="round"/><line x1="63.17" y1="24.16" x2="67.93" y2="14.81" stroke="#3EC6B6" stroke-width="2.3" stroke-linecap="round"/><line x1="67.05" y1="26.54" x2="73.22" y2="18.04" stroke="#46C2B2" stroke-width="2.3" stroke-linecap="round"/><line x1="70.51" y1="29.49" x2="77.93" y2="22.07" stroke="#51BDAD" stroke-width="2.3" stroke-linecap="round"/><line x1="73.46" y1="32.95" x2="81.96" y2="26.78" stroke="#5DB7A8" stroke-width="2.3" stroke-linecap="round"/><line x1="75.84" y1="36.83" x2="85.19" y2="32.07" stroke="#6BB1A2" stroke-width="2.3" stroke-linecap="round"/><line x1="77.58" y1="41.04" x2="87.57" y2="37.79" stroke="#79AA9B" stroke-width="2.3" stroke-linecap="round"/><line x1="78.64" y1="45.46" x2="89.01" y2="43.82" stroke="#89A394" stroke-width="2.3" stroke-linecap="round"/><line x1="79.00" y1="50.00" x2="89.50" y2="50.00" stroke="#999B8C" stroke-width="2.3" stroke-linecap="round"/><line x1="78.64" y1="54.54" x2="89.01" y2="56.18" stroke="#A99385" stroke-width="2.3" stroke-linecap="round"/><line x1="77.58" y1="58.96" x2="87.57" y2="62.21" stroke="#B98C7E" stroke-width="2.3" stroke-linecap="round"/><line x1="75.84" y1="63.17" x2="85.19" y2="67.93" stroke="#C78577" stroke-width="2.3" stroke-linecap="round"/><line x1="73.46" y1="67.05" x2="81.96" y2="73.22" stroke="#D57F71" stroke-width="2.3" stroke-linecap="round"/><line x1="70.51" y1="70.51" x2="77.93" y2="77.93" stroke="#E1796C" stroke-width="2.3" stroke-linecap="round"/><line x1="67.05" y1="73.46" x2="73.22" y2="81.96" stroke="#EC7467" stroke-width="2.3" stroke-linecap="round"/><line x1="63.17" y1="75.84" x2="67.93" y2="85.19" stroke="#F47063" stroke-width="2.3" stroke-linecap="round"/><line x1="58.96" y1="77.58" x2="62.21" y2="87.57" stroke="#FA6D60" stroke-width="2.3" stroke-linecap="round"/><line x1="54.54" y1="78.64" x2="56.18" y2="89.01" stroke="#FE6C5F" stroke-width="2.3" stroke-linecap="round"/><line x1="50.00" y1="79.00" x2="50.00" y2="89.50" stroke="#FF6B5E" stroke-width="2.3" stroke-linecap="round"/><line x1="45.46" y1="78.64" x2="43.82" y2="89.01" stroke="#FE6C5F" stroke-width="2.3" stroke-linecap="round"/><line x1="41.04" y1="77.58" x2="37.79" y2="87.57" stroke="#FA6D60" stroke-width="2.3" stroke-linecap="round"/><line x1="36.83" y1="75.84" x2="32.07" y2="85.19" stroke="#F47063" stroke-width="2.3" stroke-linecap="round"/><line x1="32.95" y1="73.46" x2="26.78" y2="81.96" stroke="#EC7467" stroke-width="2.3" stroke-linecap="round"/><line x1="29.49" y1="70.51" x2="22.07" y2="77.93" stroke="#E1796C" stroke-width="2.3" stroke-linecap="round"/><line x1="26.54" y1="67.05" x2="18.04" y2="73.22" stroke="#D57F71" stroke-width="2.3" stroke-linecap="round"/><line x1="24.16" y1="63.17" x2="14.81" y2="67.93" stroke="#C78577" stroke-width="2.3" stroke-linecap="round"/><line x1="22.42" y1="58.96" x2="12.43" y2="62.21" stroke="#B98C7E" stroke-width="2.3" stroke-linecap="round"/><line x1="21.36" y1="54.54" x2="10.99" y2="56.18" stroke="#A99385" stroke-width="2.3" stroke-linecap="round"/><line x1="21.00" y1="50.00" x2="10.50" y2="50.00" stroke="#999B8C" stroke-width="2.3" stroke-linecap="round"/><line x1="21.36" y1="45.46" x2="10.99" y2="43.82" stroke="#89A394" stroke-width="2.3" stroke-linecap="round"/><line x1="22.42" y1="41.04" x2="12.43" y2="37.79" stroke="#79AA9B" stroke-width="2.3" stroke-linecap="round"/><line x1="24.16" y1="36.83" x2="14.81" y2="32.07" stroke="#6BB1A2" stroke-width="2.3" stroke-linecap="round"/><line x1="26.54" y1="32.95" x2="18.04" y2="26.78" stroke="#5DB7A8" stroke-width="2.3" stroke-linecap="round"/><line x1="29.49" y1="29.49" x2="22.07" y2="22.07" stroke="#51BDAD" stroke-width="2.3" stroke-linecap="round"/><line x1="32.95" y1="26.54" x2="26.78" y2="18.04" stroke="#46C2B2" stroke-width="2.3" stroke-linecap="round"/><line x1="36.83" y1="24.16" x2="32.07" y2="14.81" stroke="#3EC6B6" stroke-width="2.3" stroke-linecap="round"/><line x1="41.04" y1="22.42" x2="37.79" y2="12.43" stroke="#38C9B9" stroke-width="2.3" stroke-linecap="round"/><line x1="45.46" y1="21.36" x2="43.82" y2="10.99" stroke="#34CABA" stroke-width="2.3" stroke-linecap="round"/></g><text class="bm-k" x="48.7" y="50" text-anchor="middle" dominant-baseline="central" font-family="'IBM Plex Sans',system-ui,sans-serif" font-weight="700" font-size="34" fill="#FF6B5E">k</text></svg>`;
let obMicTimer = null, obMicPeak = 0;

function obModelCards() {
  const models = state.models || [];
  if (!models.length) return `<div class="dict-empty">Список моделей недоступний</div>`;
  return models.map((m, i) => {
    const on = state.onb.model === m.id;
    const rec = m.id === "uk-ft";
    const meta = m.installed ? "на диску" : "не завантажена — завантажте у Налаштуваннях";
    const status = m.active ? "активна" : (m.installed ? "на диску" : "не завантажена");
    return `<div class="mcard${on ? " on" : ""}" role="radio" aria-checked="${on ? "true" : "false"}"
      aria-label="${esc(m.label)} — ${esc(m.size)} — ${status}" tabindex="${on ? 0 : -1}" data-mid="${esc(m.id)}">
      <div class="chk">${svg(ICON.check, 12)}</div>
      ${rec ? `<div class="ob-rec">Радимо</div>` : ""}
      <div class="lab">${esc(m.label)}</div>
      <div class="hint">${esc(m.size)} · ${esc(meta)}</div></div>`;
  }).join("");
}
function obPane(key) {
  const s = state.settings;
  if (key === "welcome") return `<h1>Вітаємо у <span>KuubWave</span></h1>
    <div class="ob-sub">Диктування українською та англійською, що працює будь-де на екрані. Розпізнавання йде на вашому GPU — жодне слово не залишає цей компʼютер.</div>
    <div class="ob-feat"><div class="fi">${svg(ICON.shield)}</div><div><div class="ft">Приватно й офлайн</div><div class="fd">Аудіо обробляється локально, без хмари</div></div></div>
    <div class="ob-feat"><div class="fi">${svg(ICON.chip)}</div><div><div class="ft">Швидко на GPU</div><div class="fd">Розпізнавання за частку секунди</div></div></div>
    <div class="ob-feat"><div class="fi">${svg(ICON.overlay)}</div><div><div class="ft">Будь-де на екрані</div><div class="fd">Затисніть клавішу — і диктуйте в будь-яке поле</div></div></div>`;
  if (key === "lang") return `<h1>Визначення мови</h1>
    <div class="ob-sub">KuubWave сам визначає, українською ви говорите чи англійською, і не змушує перемикатися вручну. Це можна змінити будь-коли в Налаштуваннях.</div>
    <div class="ob-toggle">
      <div class="tt"><div class="th2">Автоматичне визначення мови</div>
        <div class="td">Розпізнавати українську й англійську без ручного перемикання</div></div>
      <button class="tg ${s.autoLang ? "on" : ""}" role="switch" aria-checked="${s.autoLang ? "true" : "false"}"
        aria-label="Автоматичне визначення мови" id="obAutoLang"><span class="th"></span></button></div>`;
  if (key === "model") return `<h1>Оберіть модель</h1>
    <div class="ob-sub">Більша — точніша, менша — швидша. Обрати можна лише вже завантажену модель; решту завантажите пізніше в Налаштуваннях.</div>
    <div class="mcards" id="obMcards" role="radiogroup" aria-label="Модель розпізнавання">${obModelCards()}</div>`;
  if (key === "mic") return `<h1>Перевірка мікрофона</h1>
    <div class="ob-sub">Переконаймося, що мікрофон вас чує. Натисніть «Перевірити» і скажіть кілька слів.</div>
    <div class="ob-checkrow"><div class="ci">${svg(ICON.chip)}</div>
      <div class="ct"><div class="ck">Обробка</div><div class="cd">${esc(state.gpu)} · локально</div></div>
      <div class="ob-okpill">${svg(ICON.check, 14)}Готово</div></div>
    <div class="ob-checkrow"><div class="ci">${svg(ICON.mic)}</div>
      <div class="ct"><div class="ck">Мікрофон</div><div class="cd" id="obMicHint">Натисніть «Перевірити» і скажіть кілька слів</div></div>
      <button class="btn ghost" id="obMicBtn">Перевірити</button></div>
    <div class="level" style="margin-top:2px"><div class="fill" id="obLvl"></div><div class="th"></div></div>`;
  if (key === "hotkey") return `<h1>Гаряча клавіша</h1>
    <div class="ob-sub">Утримуйте цю клавішу, щоб диктувати. Відпустіть — текст зʼявиться там, де курсор.</div>
    <div class="ob-hkwrap"><span class="keycap" id="obCap">${esc(state.hotkey)}</span>
      <div class="htx"><div style="font-size:13.5px;font-weight:600">Утримувати для диктування</div>
        <div style="font-size:12px;color:var(--t3);margin-top:2px">Натисніть «Змінити» та виконайте комбінацію</div></div>
      <button class="btn ghost" id="obHkBtn">Змінити</button></div>`;
  if (key === "license") {
    const l = state.license || {};
    const note = l.licensed
      ? `<div class="note ok">${svg(ICON.shield, 15)}Ліцензія активна${typeof l.daysLeft === "number" ? ` · залишилось ${l.daysLeft} дн.` : ""}</div>`
      : `<div class="note warn">${svg(ICON.warn, 15)}${l.reason === "expired" ? "Ліцензію прострочено — введіть новий ключ" : "Ліцензія ще не активована"}</div>`;
    return `<h1>Ліцензія</h1>
      <div class="ob-sub">Введіть ключ, який ви отримали після покупки. Це не обовʼязково зараз — можна пропустити й активувати згодом у Налаштуваннях.</div>
      ${note}
      <input class="inp" id="obLic" style="margin-top:14px" placeholder="Вставте ключ ліцензії" aria-label="Ключ ліцензії" value="${esc(state.onb.lic || "")}">
      <div class="note err" id="obLicErr" style="margin-top:12px;display:none"></div>
      <div class="ob-licalt"><span>Ще не купили?</span><span>Натисніть «Пропустити», щоб продовжити без ключа.</span></div>`;
  }
  return `<div class="ob-done"><div class="ob-donemark">${svg(ICON.check, 44)}</div>
    <h1>Все готово!</h1>
    <div class="ob-sub" style="margin-bottom:8px">KuubWave працює у треї. Спробуйте прямо зараз:</div>
    <div class="ob-donekbd">Затисніть <span class="key">${esc(state.hotkey)}</span> і говоріть</div></div>`;
}
function obRender() {
  const root = document.getElementById("obRoot");
  if (!root || !state.onb) return;
  const i = state.onb.i, total = OB_STEPS.length, key = OB_STEPS[i];
  root.innerHTML = `
    <aside class="ob-rail">
      <div class="ob-rbrand">${OB_BRANDMARK}<b>kuubwave</b></div>
      <div class="ob-steps" role="group" aria-label="Прогрес знайомства">
        ${OB_STEPS.map((k, idx) => `<div class="ob-step ${idx === i ? "on" : ""} ${idx < i ? "done" : ""}"${idx === i ? ' aria-current="step"' : ""}>
          <div class="num" aria-hidden="true">${idx < i ? svg(ICON.check, 14) : (idx + 1)}</div><div class="lb">${OB_LABEL[k]}</div></div>`).join("")}
      </div>
      <div class="ob-rfoot"><span class="d"></span>Локально · приватно · офлайн</div>
    </aside>
    <div class="ob-main">
      <div class="ob-body"><div class="ob-pane" id="obPane">${obPane(key)}</div></div>
      <div class="ob-foot">
        <div class="lft"><button class="ob-back" id="obBack" style="visibility:${i === 0 ? "hidden" : "visible"}">← Назад</button></div>
        <div class="ob-mid"><span class="ob-count">Крок ${i + 1} з ${total}</span>
          <div class="ob-dots" aria-hidden="true">${OB_STEPS.map((_, idx) => `<div class="ob-dot ${idx === i ? "on" : ""}"></div>`).join("")}</div></div>
        <div class="rgt">${i < total - 1 ? `<button class="ob-skip" id="obSkip">Пропустити</button>` : ""}<button class="btn pri" id="obNext">${i === total - 1 ? "Завершити" : (i === 0 ? "Почати" : "Далі")}</button></div>
      </div>
    </div>`;
  obWire(key);
  // focus moves to each step's heading on advance (assistive tech announces it)
  requestAnimationFrame(() => { const h = root.querySelector("#obPane h1"); if (h) { h.setAttribute("tabindex", "-1"); h.focus(); } });
}
function obWire(key) {
  const root = document.getElementById("obRoot");
  root.querySelector("#obNext").onclick = obNext;
  const back = root.querySelector("#obBack"); if (back) back.onclick = obBack;
  const skip = root.querySelector("#obSkip"); if (skip) skip.onclick = obSkip;
  if (key === "lang") {
    const tg = root.querySelector("#obAutoLang");
    tg.onclick = () => {
      state.settings.autoLang = !state.settings.autoLang;
      tg.classList.toggle("on", state.settings.autoLang);
      tg.setAttribute("aria-checked", state.settings.autoLang ? "true" : "false");
      saveSettings();  // same save_settings payload the General tab uses
    };
  }
  if (key === "model") root.querySelectorAll("#obMcards .mcard").forEach((c) => {
    c.onclick = () => obModelSelect(c.dataset.mid);
    c.onkeydown = (e) => obModelKey(e, c.dataset.mid);
  });
  if (key === "mic") { const b = root.querySelector("#obMicBtn"); b.onclick = () => obMicTest(b); }
  if (key === "hotkey") { const b = root.querySelector("#obHkBtn"); b.onclick = () => obCaptureHotkey(b); }
  if (key === "license") { const lic = root.querySelector("#obLic"); lic.oninput = () => state.onb.lic = lic.value; }
}
async function obModelSelect(id) {
  const m = (state.models || []).find((x) => x.id === id);
  if (!m) return;
  // downloads stay in Settings: an uninstalled model is not activated here, only
  // pointed at where to get it — no multi-GB pull kicked off inside onboarding
  if (!m.installed) { toast("Спершу завантажте цю модель у Налаштуваннях → Модель"); return; }
  const r = await api("activate_model", id);
  if (r && r.ok === false) { toast(r.error || "не вдалося"); return; }
  state.models = (await api("list_models")) || state.models;
  state.onb.model = id;
  state.settings.model = id;
  const host = document.getElementById("obMcards");
  if (host) {
    host.innerHTML = obModelCards();
    host.querySelectorAll(".mcard").forEach((c) => {
      c.onclick = () => obModelSelect(c.dataset.mid);
      c.onkeydown = (e) => obModelKey(e, c.dataset.mid);
    });
    const sel = host.querySelector(".mcard.on"); if (sel) sel.focus();
  }
}
function obModelKey(e, id) {
  const cards = [...document.querySelectorAll("#obMcards .mcard")];
  const idx = cards.findIndex((c) => c.dataset.mid === id);
  if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") { e.preventDefault(); obModelSelect(id); return; }
  let ni = -1;
  if (e.key === "ArrowDown" || e.key === "ArrowRight") ni = (idx + 1) % cards.length;
  else if (e.key === "ArrowUp" || e.key === "ArrowLeft") ni = (idx - 1 + cards.length) % cards.length;
  if (ni < 0) return;
  e.preventDefault();
  cards.forEach((c) => c.tabIndex = -1);
  cards[ni].tabIndex = 0; cards[ni].focus();
}
async function obMicTest(btn) {
  const lvl = document.getElementById("obLvl"), hint = document.getElementById("obMicHint");
  if (obMicTimer) {
    obStopMic();
    btn.textContent = "Перевірити"; btn.classList.remove("pri"); btn.classList.add("ghost");
    if (lvl) lvl.style.transform = "scaleX(0)";
    if (hint) hint.textContent = "Натисніть «Перевірити» і скажіть кілька слів";
    return;
  }
  await api("mic_test", true);
  btn.textContent = "Стоп"; btn.classList.remove("ghost"); btn.classList.add("pri");
  obMicPeak = 0;
  // identical meter maths to the Microphone settings tab: full scale = 0.1 RMS,
  // the 0.02 "hears you" threshold sits on the tick
  obMicTimer = setInterval(async () => {
    const v = await api("get_input_level");
    obMicPeak = Math.max(obMicPeak, v);
    const f = document.getElementById("obLvl");
    if (f) { f.style.transform = `scaleX(${Math.min(1, v / 0.1)})`; f.style.background = v > 0.02 ? "var(--aqua)" : "var(--coral)"; }
    const h = document.getElementById("obMicHint");
    if (h) h.textContent = obMicPeak > 0.02 ? "Мікрофон чує голос ✓"
      : "Говоріть у мікрофон… Якщо смужка майже не рухається — підніміть гучність мікрофона у Windows.";
  }, 100);
}
function obStopMic() {
  if (!obMicTimer) return;
  clearInterval(obMicTimer); obMicTimer = null;
  api("mic_test", false);  // release the mic when leaving the step
}
async function obCaptureHotkey(btn) {
  btn.classList.remove("ghost"); btn.classList.add("pri");
  btn.textContent = "Слухаю…";
  const combo = await api("capture_hotkey");
  state.hotkey = combo || state.hotkey;
  if (state.onb) state.onb.hotkey = state.hotkey;
  btn.classList.remove("pri"); btn.classList.add("ghost");
  btn.textContent = "Змінити";
  const cap = document.getElementById("obCap"); if (cap) cap.textContent = state.hotkey;
  paintTopHint();
}
async function obNext() {
  obStopMic();
  const key = OB_STEPS[state.onb.i];
  // license is optional; if a key was typed, try it before advancing and keep
  // the user on the step if it is rejected, but never force activation
  if (key === "license") {
    const val = (state.onb.lic || "").trim();
    if (val) {
      const res = await api("activate_license", val);
      if (res && res.ok) {
        state.license = { licensed: true, daysLeft: res.daysLeft, exp: res.exp,
                          reason: "ok", customer: res.customer || "" };
        toast("Ліцензію активовано");
      } else {
        const err = document.getElementById("obLicErr");
        if (err) { err.style.display = "flex"; err.innerHTML = svg(ICON.warn, 15) + esc((res && res.error) || "Помилка активації"); }
        return;
      }
    }
  }
  if (state.onb.i < OB_STEPS.length - 1) { state.onb.i++; obRender(); }
  else obFinish();
}
function obBack() {
  obStopMic();
  const err = document.getElementById("obLicErr"); if (err) err.style.display = "none";
  if (state.onb.i > 0) { state.onb.i--; obRender(); }
}
async function obFinishGate() {
  await api("finish_onboarding");
  state.onboarded = true;
}
async function obFinish() { await obFinishGate(); obClose(); }
async function obSkip() { obStopMic(); await obFinishGate(); obClose(); }
function obClose() {
  obStopMic();
  state.onb = null; state.page = "home";
  document.body.classList.remove("ob-open");
  const root = document.getElementById("obRoot");
  if (root) { root.setAttribute("aria-hidden", "true"); root.innerHTML = ""; }
  renderNav(); render();
  // land on Home with focus on its heading
  requestAnimationFrame(() => { const h = document.querySelector(".htitle"); if (h) { h.setAttribute("tabindex", "-1"); h.focus(); } });
}
function openOnboarding() {
  stopMicTest();  // silence any settings mic test still running
  const active = (state.models || []).find((m) => m.active);
  state.onb = { i: 0, hotkey: state.hotkey, lic: "",
                model: active ? active.id : (state.models[0] ? state.models[0].id : "") };
  // clear the chrome underneath so exactly one <h1> (the wizard's) is in the DOM
  const body = document.getElementById("body"); if (body) body.innerHTML = "";
  document.body.classList.add("ob-open");
  const root = document.getElementById("obRoot");
  if (root) root.setAttribute("aria-hidden", "false");
  obRender();
}
window.openOnboarding = openOnboarding;

// ---- live status poll ----
async function tickStatus() {
  const st = await api("get_status");
  if (!st || st === state.homeState) return;
  // respect a manual preview hold; don't yank the hero away from the user
  if (Date.now() < (state.manualHoldUntil || 0)) return;
  if (state.page === "home") setHomeState(st);
  else state.homeState = st;
}
let micWarnTicks = 0;
function pollStatus() {
  setInterval(() => {
    if (document.hidden) return;
    tickStatus();
    // rides the status timer, but only every 4th pass (~2s): the flag changes
    // at most once per dictation, so 2x/s would be bridge traffic for nothing
    if (micWarnTicks++ % 4 === 0) tickMicWarning();
  }, 500);
}
// back from the tray: state may be minutes stale, so refresh once immediately
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  tickStatus(); tickDownload(); tickMicWarning();
});

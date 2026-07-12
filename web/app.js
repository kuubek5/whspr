// app.js — whspr web UI. State + render + bridge to Python (pywebview).
// Falls back to mock data when opened in a plain browser (no pywebview.api).

const PAGES = { home: "Головна", history: "Історія", dictionary: "Словник", settings: "Налаштування" };
const SUN = '<circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path>';
const MOON = '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z"></path>';

const state = {
  theme: "dark", page: "home", homeState: "idle", recordSecs: 0,
  gpu: "…", hotkey: "Fn", listening: false,
  stats: { wordsToday: 0, dictations: 0, wordsTotal: 0, wpm: 0 },
  recent: [], history: [],
  settings: { autostart: true, floatingPanel: true, sound: false, autoLang: true,
              model: "uk-ft", gpuDevice: "RTX 4070", device: "cuda", inputDevice: "", micOnDemand: false,
              backupKeyVisible: false, backupKey: "" },
  devices: [],
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
function mock(method, args) {
  if (method === "bootstrap") return {
    theme: "dark", gpu: "RTX 3070", hotkey: "Fn",
    status: "idle",
    stats: { wordsToday: 2481, dictations: 37, wordsTotal: 184920, wpm: 132 },
    recent: [
      { time: "Сьогодні, 14:32", text: "зателефонувати Оксані до п'ятниці щодо звіту" },
      { time: "Сьогодні, 13:10", text: "додати пункт про бекапи в документацію" },
      { time: "Сьогодні, 11:48", text: "потрібно оновити прошивку квадрокоптера" },
      { time: "Вчора, 19:20", text: "нагадати купити фотополімер для друку" },
    ],
    history: [
      { id: 3, time: "14:32", lang: "uk", duration: "3.2с", text: "зателефонувати Оксані до п'ятниці щодо звіту" },
      { id: 2, time: "13:10", lang: "uk", duration: "2.1с", text: "додати пункт про бекапи в документацію" },
      { id: 1, time: "11:48", lang: "uk", duration: "1.9с", text: "потрібно оновити прошивку квадрокоптера" },
    ],
    settings: state.settings,
    devices: [{ name: "Мікрофон (Realtek Audio)" }, { name: "Вхід (XONAR SOUND CARD)" },
              { name: "OnePlus 9R Hands-Free" }],
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
  return null;
}

// ---- boot ----
async function boot() {
  const b = await api("bootstrap");
  state.theme = b.theme || "dark";
  state.gpu = b.gpu || "GPU";
  state.hotkey = b.hotkey || "Fn";
  state.stats = b.stats; state.recent = b.recent; state.history = b.history;
  state.settings = Object.assign(state.settings, b.settings || {});
  state.devices = b.devices || [];
  state.dictionary = b.dictionary; state.homeState = b.status || "idle";
  applyTheme(); document.getElementById("gpuBadge").textContent = "Локально · " + state.gpu;
  render(); pollStatus();
}
window.addEventListener("pywebviewready", boot);
document.addEventListener("DOMContentLoaded", () => { if (!hasApi()) boot(); });

// ---- theme + nav ----
function applyTheme() {
  document.documentElement.setAttribute("data-theme", state.theme);
  document.getElementById("themeIcon").innerHTML = state.theme === "dark" ? SUN : MOON;
}
document.getElementById("themeToggle").onclick = () => {
  state.theme = state.theme === "dark" ? "light" : "dark";
  applyTheme(); api("set_theme", state.theme);
};
const nav = document.getElementById("nav");
const indicator = document.getElementById("navIndicator");
function moveIndicator() {
  const btn = nav.querySelector(`[data-page="${state.page}"]`);
  indicator.style.top = btn.offsetTop + "px";
}
nav.querySelectorAll(".nav-item").forEach((btn) => {
  btn.onclick = () => {
    state.page = btn.dataset.page;
    nav.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b === btn));
    document.getElementById("pageTitle").textContent = PAGES[state.page];
    moveIndicator(); render();
  };
});

// ---- render dispatch ----
function render() {
  moveIndicator();
  const body = document.getElementById("body");
  body.innerHTML = "";
  const page = document.createElement("div");
  page.className = "page";
  body.appendChild(page);
  ({ home: renderHome, history: renderHistory, dictionary: renderDictionary, settings: renderSettings }[state.page])(page);
}
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---- HOME ----
function renderHome(el) {
  el.innerHTML = `
    <div class="hero">
      <div class="hero-center" id="heroCenter"></div>
      <div class="preview-row">
        <button class="preview-btn" data-s="idle">Очікування</button>
        <button class="preview-btn" data-s="recording">Запис</button>
        <button class="preview-btn" data-s="transcribing">Розпізнавання</button>
      </div>
    </div>
    <div class="stats-grid">
      ${statTile("Слів сьогодні", "wordsToday")}
      ${statTile("Диктовок", "dictations")}
      ${statTile("Слів усього", "wordsTotal")}
      ${statTile("Слів/хв", "wpm")}
    </div>
    <div class="card feed-card">
      <div class="feed-header">Останні диктовки</div>
      ${state.recent.length ? state.recent.map((r) => `<div class="feed-row"><div class="feed-time mono">${esc(r.time)}</div><div class="feed-text mono">${esc(r.text)}</div></div>`).join("")
        : `<div class="empty-state"><div class="empty-title">Ще немає диктовок</div><div class="empty-sub">Затисніть ${esc(state.hotkey)} і почніть говорити</div></div>`}
    </div>`;
  el.querySelectorAll(".preview-btn").forEach((b) => b.onclick = () => {
    state.manualHoldUntil = Date.now() + 6000;  // let the manual preview stay ~6s
    setHomeState(b.dataset.s);
  });
  renderHero(); countUpStats();
  el.querySelectorAll(".preview-btn").forEach((b) => b.classList.toggle("active", b.dataset.s === state.homeState));
}
function statTile(label, key) {
  return `<div class="stat-tile"><div class="stat-label">${label}</div><div class="stat-value mono" data-stat="${key}">0</div></div>`;
}
function renderHero() {
  const h = document.getElementById("heroCenter");
  if (!h) return;
  if (state.homeState === "loading") {
    h.innerHTML = `<div class="idle-dot"></div>
      <div class="hero-mic"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v1a7 7 0 0 1-14 0v-1"></path><line x1="12" y1="18" x2="12" y2="22"></line><line x1="8" y1="22" x2="16" y2="22"></line></svg></div>
      <div class="hero-title">Завантаження моделі…</div>
      <div class="hero-sub">за мить усе буде готово</div>`;
  } else if (state.homeState === "idle") {
    h.innerHTML = `<div class="idle-dot"></div>
      <div class="hero-mic"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v1a7 7 0 0 1-14 0v-1"></path><line x1="12" y1="18" x2="12" y2="22"></line><line x1="8" y1="22" x2="16" y2="22"></line></svg></div>
      <div class="hero-title">Натисніть і утримуйте ${esc(state.hotkey)}</div>
      <div class="hero-sub">щоб почати диктування будь-де на екрані</div>`;
  } else if (state.homeState === "recording") {
    h.innerHTML = `<div class="rec-timer mono">${fmtTime(state.recordSecs)}</div>
      <div class="wave-row">${waveBars(40)}</div>
      <div class="rec-label"><span class="rec-dot"></span>Запис · відпустіть ${esc(state.hotkey)}, щоб завершити</div>`;
  } else {
    h.innerHTML = `<div class="shimmer" style="width:220px"></div>
      <div class="shimmer" style="width:140px"></div>
      <div class="transcribing-label">Розпізнаю мовлення на GPU…</div>`;
  }
}
function waveBars(n) {
  let s = "";
  for (let i = 0; i < n; i++) {
    const dur = 0.6 + Math.random() * 0.7, delay = Math.random() * 0.5;
    s += `<div class="wave-bar" style="animation-duration:${dur}s;animation-delay:-${delay}s"></div>`;
  }
  return s;
}
const fmtTime = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
let recTimer = null;
function setHomeState(s) {
  state.homeState = s;
  if (s === "recording") { state.recordSecs = 0; clearInterval(recTimer);
    recTimer = setInterval(() => { state.recordSecs++; const t = document.querySelector(".rec-timer"); if (t) t.textContent = fmtTime(state.recordSecs); }, 1000);
  } else clearInterval(recTimer);
  if (state.page === "home") {
    renderHero();
    document.querySelectorAll(".preview-btn").forEach((b) => b.classList.toggle("active", b.dataset.s === s));
  }
}
let statsAnimated = false;
function countUpStats() {
  const dur = 1400, start = performance.now();
  const targets = state.stats;
  function step(now) {
    const p = Math.min(1, (now - start) / dur), e = 1 - Math.pow(1 - p, 3);
    document.querySelectorAll("[data-stat]").forEach((el) => {
      el.textContent = Math.round(targets[el.dataset.stat] * e).toLocaleString("uk");
    });
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// ---- HISTORY ----
function renderHistory(el) {
  if (!state.history.length) {
    el.innerHTML = `<div class="empty-state">
      <svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"></path><polyline points="3 4 3 9 8 9"></polyline><polyline points="12 7 12 12 16 14"></polyline></svg>
      <div class="empty-title">Історія порожня</div>
      <div class="empty-sub">Ваші диктовки зʼявлятимуться тут</div></div>`;
    return;
  }
  el.innerHTML = `<div class="hist-header mono">${state.history.length} диктовок</div>` +
    state.history.map((it) => `
      <div class="hist-card" data-id="${it.id}">
        <div class="hist-actions">
          <button class="chip-btn copy"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button>
          <button class="chip-btn del"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path></svg></button>
        </div>
        <div class="meta-row mono"><span>${esc(it.time)}</span><span>·</span><span class="lang-chip">${esc((it.lang||"uk").toUpperCase())}</span><span>·</span><span>${esc(it.duration)}</span></div>
        <div class="hist-text mono">${esc(it.text)}</div>
      </div>`).join("");
  el.querySelectorAll(".hist-card").forEach((card) => {
    const id = +card.dataset.id;
    card.querySelector(".copy").onclick = (e) => {
      const btn = e.currentTarget; api("history_copy", id);
      btn.classList.add("ok"); btn.innerHTML = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
      setTimeout(() => renderHistory(el), 1400);
    };
    card.querySelector(".del").onclick = () => { api("history_delete", id); state.history = state.history.filter((h) => h.id !== id); renderHistory(el); };
  });
}

// ---- DICTIONARY ----
function renderDictionary(el) {
  el.innerHTML = `
    <div class="card">
      <div class="section-title">Хотворди</div>
      <div class="section-sub">Терміни, які модель має розпізнавати з підвищеним пріоритетом — розділяйте комами</div>
      <textarea class="hotwords-ta mono" id="hotwords">${esc(state.dictionary.hotwords)}</textarea>
    </div>
    <div class="card">
      <div class="cmd-head">
        <div><div class="section-title">Голосові команди</div>
        <div class="section-sub" style="margin-bottom:0">Промовте фразу зліва — whspr вставить символ праворуч. Наприклад: «нова думка» = ⏎</div></div>
        <button class="add-btn" id="addCmd"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>Додати</button>
      </div>
      <div id="cmdList"></div>
    </div>
    <div style="text-align:right"><button class="hotkey-btn" id="saveDict" style="background:var(--accent);color:#fff;border:none">Зберегти</button></div>`;
  renderCmds();
  el.querySelector("#addCmd").onclick = () => { state.dictionary.commands.push({ phrase: "", result: "" }); renderCmds(); };
  el.querySelector("#saveDict").onclick = () => {
    state.dictionary.hotwords = el.querySelector("#hotwords").value;
    api("save_dictionary", state.dictionary.hotwords, state.dictionary.commands);
    const b = el.querySelector("#saveDict"); b.textContent = "Збережено ✓"; setTimeout(() => (b.textContent = "Зберегти"), 1500);
  };
}
function renderCmds() {
  const list = document.getElementById("cmdList"); if (!list) return;
  list.innerHTML = state.dictionary.commands.map((c, i) => `
    <div class="cmd-row" data-i="${i}">
      <input class="cmd-input mono phrase" value="${esc(c.phrase)}" placeholder="фраза">
      <span class="cmd-eq">=</span>
      <input class="cmd-input cmd-result mono result" value="${esc(c.result)}" placeholder="⏎">
      <button class="chip-btn del"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
    </div>`).join("");
  list.querySelectorAll(".cmd-row").forEach((row) => {
    const i = +row.dataset.i;
    row.querySelector(".phrase").oninput = (e) => (state.dictionary.commands[i].phrase = e.target.value);
    row.querySelector(".result").oninput = (e) => (state.dictionary.commands[i].result = e.target.value);
    row.querySelector(".del").onclick = () => { state.dictionary.commands.splice(i, 1); renderCmds(); };
  });
}

// ---- SETTINGS ----
function renderSettings(el) {
  const s = state.settings;
  el.innerHTML = `
    <div class="card">
      <div class="section-title" style="margin-bottom:6px">Загальні</div>
      ${toggleRow("Запускати з Windows", "Автоматично запускати whspr при вході в систему", "autostart")}
      ${toggleRow("Показувати плаваючу панель", "Індикатор запису поверх усіх вікон", "floatingPanel")}
      ${toggleRow("Звук при завершенні диктовки", "Короткий сигнал, коли текст готовий", "sound")}
      ${toggleRow("Автоматичне визначення мови", "whspr сам визначить українську чи англійську", "autoLang", true)}
    </div>
    <div class="card">
      <div class="section-title" style="margin-bottom:6px">Гаряча клавіша</div>
      <div class="setting-row" style="border:none">
        <div><div class="setting-label">Утримувати для диктування</div><div class="setting-hint">Натисніть кнопку та виконайте потрібну комбінацію</div></div>
        <button class="hotkey-btn mono" id="hotkeyBtn">${esc(state.hotkey)}</button>
      </div>
    </div>
    <div class="card">
      <div class="section-title" style="margin-bottom:6px">Мікрофон</div>
      <div class="setting-row">
        <div><div class="setting-label">Пристрій вводу</div><div class="setting-hint">Джерело звуку для диктування</div></div>
        <select class="select" id="selMic"></select>
      </div>
      ${toggleRow("Відкривати мікрофон лише під час запису", "Прибирає значок мікрофона в треї; можливе зрізання перших мілісекунд фрази", "micOnDemand", true)}
    </div>
    <div class="card">
      <div class="section-title" style="margin-bottom:6px">Модель розпізнавання</div>
      <div class="setting-row">
        <div><div class="setting-label">Модель для української</div><div class="setting-hint">uk-ft — донавчена на розмовній українській</div></div>
        <select class="select" id="selModel">
          <option value="stock">stock-large-v3</option>
          <option value="uk-ft">uk-ft-v2 (рекомендовано)</option>
        </select>
      </div>
      <div class="setting-row" style="border:none">
        <div><div class="setting-label">Пристрій обробки</div><div class="setting-hint">Де рахувати модель: GPU швидко, CPU повільний запасний. Уся обробка локально</div></div>
        <select class="select" id="selGpu">
          <option value="cuda">${esc(state.gpu)} (GPU)</option>
          <option value="cpu">CPU (запасний варіант)</option>
        </select>
      </div>
    </div>
    <div class="card">
      <div class="section-title" style="margin-bottom:10px">Приватність</div>
      <div class="privacy-note"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 4 5v6c0 5 3.5 8.5 8 11 4.5-2.5 8-6 8-11V5l-8-3Z"></path></svg>Диктовки ніколи не залишають цей пристрій</div>
      <div class="setting-row" style="border:none">
        <div><div class="setting-label">Ключ шифрування резервної копії</div><div class="setting-hint">Необов'язково — для локального шифрованого бекапу</div></div>
        <div class="key-wrap">
          <input class="key-input mono" id="keyInput" type="password" value="${esc(s.backupKey)}" readonly>
          <button class="chip-btn" id="keyEye"></button>
        </div>
      </div>
    </div>`;
  el.querySelectorAll(".toggle").forEach((t) => t.onclick = () => {
    const k = t.dataset.key; s[k] = !s[k]; t.classList.toggle("on", s[k]); saveSettings();
  });
  const selM = el.querySelector("#selModel"); selM.value = s.model; selM.onchange = () => { s.model = selM.value; saveSettings(); };
  const selG = el.querySelector("#selGpu"); selG.value = s.device || "cuda"; selG.onchange = () => { s.device = selG.value; saveSettings(); };
  const selMic = el.querySelector("#selMic");
  selMic.innerHTML = `<option value="">Системний за замовчуванням</option>` +
    state.devices.map((d) => `<option value="${esc(d.name)}">${esc(d.name)}</option>`).join("");
  selMic.value = s.inputDevice || "";
  selMic.onchange = () => { s.inputDevice = selMic.value; saveSettings(); };
  el.querySelector("#hotkeyBtn").onclick = captureHotkey;
  const eye = el.querySelector("#keyEye"); setEye(eye);
  eye.onclick = () => { s.backupKeyVisible = !s.backupKeyVisible;
    el.querySelector("#keyInput").type = s.backupKeyVisible ? "text" : "password"; setEye(eye); };
}
function toggleRow(label, hint, key, last) {
  const on = state.settings[key];
  return `<div class="setting-row"${last ? ' style="border:none"' : ""}>
    <div><div class="setting-label">${label}</div><div class="setting-hint">${hint}</div></div>
    <button class="toggle ${on ? "on" : ""}" data-key="${key}"><div class="toggle-thumb"></div></button></div>`;
}
function setEye(btn) {
  btn.innerHTML = state.settings.backupKeyVisible
    ? '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M17.9 17.9A10.6 10.6 0 0 1 12 19c-7 0-11-7-11-7a19 19 0 0 1 5-5.9M9.9 4.2A9.7 9.7 0 0 1 12 4c7 0 11 7 11 7a19 19 0 0 1-2.3 3.2M14.1 14.1a3 3 0 1 1-4.2-4.2"></path><line x1="2" y1="2" x2="22" y2="22"></line></svg>'
    : '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
}
function saveSettings() { api("save_settings", JSON.parse(JSON.stringify(state.settings))); }

async function captureHotkey() {
  const btn = document.getElementById("hotkeyBtn");
  btn.classList.add("listening"); btn.textContent = "Слухаю…";
  const combo = await api("capture_hotkey");
  state.hotkey = combo || state.hotkey;
  btn.classList.remove("listening"); btn.textContent = state.hotkey;
}

// ---- live status poll ----
async function pollStatus() {
  setInterval(async () => {
    const st = await api("get_status");
    if (!st || st === state.homeState) return;
    // respect a manual preview hold; don't yank the hero away from the user
    if (Date.now() < (state.manualHoldUntil || 0)) return;
    if (state.page === "home") setHomeState(st);
    else state.homeState = st;
  }, 500);
}

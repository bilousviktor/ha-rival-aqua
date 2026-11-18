/*
 * Rival Aqua schedule editor card.
 *
 * Shows the controller's daily light curve like its own web UI and lets you add, delete, move and
 * adjust points, then saves them with rival_aqua.set_schedule (the web UI's Save button).
 * Nothing is sent to the light until Save is pressed.
 *
 *   type: custom:rival-aqua-schedule-card
 *   title: Aquarium schedule      # optional
 *   config_entry_id: ...          # optional, needed only with several controllers
 *   entity: light.aquarium        # optional alternative to config_entry_id
 *   height: 280                   # optional chart height in px
 *
 * Served and loaded by the integration itself; no build step, no dependencies.
 */

const CARD_VERSION = "0.4.0";
const DOMAIN = "rival_aqua";
const DAY = 24 * 60;
const SNAP = 5; // minutes; hold Shift while dragging for 1-minute steps

const STRINGS = {
  en: {
    title: "Light schedule",
    loading: "Reading the schedule from the controller…",
    save: "Save",
    saving: "Saving…",
    revert: "Revert",
    reload: "Reload from controller",
    saved: "Saved to the controller.",
    unsaved: "Unsaved changes",
    points: "points",
    add: "Add point at",
    delete: "Delete point",
    time: "Time",
    point: "Point",
    of: "of",
    all: "All",
    full: "The controller stores at most {n} points.",
    taken: "There is already a point at {t}.",
    lastPoint: "The schedule needs at least one point.",
    hint: "Drag a point to change its time (sideways) or level (up/down). Tap empty space, then Add, or double-tap it to add a point right away. Pick a colour above to edit only that channel.",
    saveNote: "Save writes the schedule to the controller and turns manual mode off, so the new schedule runs right away.",
    discard: "Discard unsaved changes and reload from the controller?",
    prev: "Previous point",
    next: "Next point",
    backup: "Download schedule (CSV, same as the controller's preset file)",
    restore: "Load schedule from a CSV file",
    restored: "Loaded {n} points from {file}. Check them, then press Save.",
    badFile: "Not a Rival Aqua schedule file: {why}",
  },
  uk: {
    title: "Розклад світла",
    loading: "Читаю розклад з контролера…",
    save: "Зберегти",
    saving: "Зберігаю…",
    revert: "Скасувати",
    reload: "Перечитати з контролера",
    saved: "Збережено на контролері.",
    unsaved: "Є незбережені зміни",
    points: "точок",
    add: "Додати точку о",
    delete: "Видалити точку",
    time: "Час",
    point: "Точка",
    of: "з",
    all: "Усі",
    full: "Контролер зберігає щонайбільше {n} точок.",
    taken: "Точка о {t} вже є.",
    lastPoint: "У розкладі має бути хоча б одна точка.",
    hint: "Тягніть точку вбік, щоб змінити час, або вгору/вниз, щоб змінити яскравість. Торкніться порожнього місця й натисніть «Додати» або торкніться двічі, щоб одразу додати точку. Виберіть колір угорі, щоб редагувати лише цей канал.",
    saveNote: "«Зберегти» записує розклад на контролер і вимикає ручний режим, тож новий розклад запрацює одразу.",
    discard: "Відкинути незбережені зміни й перечитати з контролера?",
    prev: "Попередня точка",
    next: "Наступна точка",
    backup: "Завантажити розклад (CSV, як файл пресету контролера)",
    restore: "Відкрити розклад із CSV-файлу",
    restored: "Завантажено {n} точок із {file}. Перевірте їх і натисніть «Зберегти».",
    badFile: "Це не файл розкладу Rival Aqua: {why}",
  },
};

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const fmt = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const parseTime = (s) => {
  const m = /^(\d{1,2}):(\d{2})/.exec(s || "");
  if (!m) return null;
  const h = +m[1];
  const min = +m[2];
  return h < 24 && min < 60 ? h * 60 + min : null;
};
const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const FALLBACK_COLORS = ["#e0e0e0", "#32cd32", "#2f6bff", "#ffd400", "#ff3b30", "#ff00ff", "#bdbdbd", "#c0ca33", "#ff7043"];

/** Relative luminance of #rrggbb (0 dark .. 1 light); light colours get an outline so they show on light themes. */
function luminance(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return 0.5;
  const n = parseInt(m[1], 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    c /= 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

/** Linear level of `series` at minute `t`, with the fixed 00:00 and 24:00 ends at 0 like the controller's chart. */
export function interpolate(points, series, t) {
  const xs = [{ t: 0, v: 0 }, ...points.map((p) => ({ t: p.t, v: p.v[series] })), { t: DAY, v: 0 }];
  for (let i = 1; i < xs.length; i++) {
    if (t <= xs[i].t) {
      const a = xs[i - 1];
      const b = xs[i];
      return b.t === a.t ? b.v : Math.round(a.v + ((b.v - a.v) * (t - a.t)) / (b.t - a.t));
    }
  }
  return 0;
}

/**
 * The controller's preset file (/user_preset.csv): a row of point times in minutes, then one row of
 * levels per channel 0-8 (8 = cooler), every value followed by a comma.
 */
export function scheduleToCsv(points, channelCount, hasFan) {
  const rows = [points.map((p) => p.t)];
  for (let ch = 0; ch < 9; ch++) {
    const s = ch < channelCount ? ch : ch === 8 && hasFan ? channelCount : -1;
    rows.push(points.map((p) => (s < 0 ? 0 : p.v[s])));
  }
  return rows.map((r) => r.map((v) => `${v},`).join("")).join("\n") + "\n";
}

/** Parse a preset CSV into editor points; throws Error with a short reason. */
export function csvToSchedule(text, channelCount, hasFan, maxPoints) {
  const rows = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => l.split(",").map((x) => x.trim()).filter((x) => x !== ""));
  const bad = (why) => {
    throw new Error(why);
  };
  if (!rows.length) bad("empty file");
  for (const row of rows) for (const x of row) if (!/^\d+$/.test(x)) bad(`unexpected value "${x.slice(0, 20)}"`);
  const times = rows[0].map(Number);
  const n = times.length;
  if (n < 1 || n > maxPoints) bad(`${n} points (1-${maxPoints} allowed)`);
  times.forEach((t, i) => {
    if (t >= 24 * 60) bad(`time ${t} is past 23:59`);
    if (i && t <= times[i - 1]) bad("times are not increasing");
  });
  const level = (ch, i) => {
    const row = rows[1 + ch];
    if (!row) return 0;
    if (row.length !== n) bad(`channel ${ch + 1} has ${row.length} values for ${n} points`);
    const v = Number(row[i]);
    if (v > 100) bad(`level ${v} is over 100`);
    return v;
  };
  return times.map((t, i) => ({
    t,
    v: [...Array.from({ length: channelCount }, (_, ch) => level(ch, i)), ...(hasFan ? [level(8, i)] : [])],
  }));
}

class RivalAquaScheduleCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._series = []; // [{name, color, light}]
    this._points = []; // [{t, v: [level per series]}] sorted by t
    this._orig = "[]";
    this._max = 16;
    this._hasFan = false;
    this._sel = null; // selected point index
    this._cursor = null; // minute picked on empty chart space
    this._focus = null; // series index being edited alone
    this._drag = null;
    this._loading = false;
    this._saving = false;
    this._loaded = false;
    this._msg = null; // {kind: "error" | "ok", text}
    this._width = 0;
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    const changed = this._config.config_entry_id !== config.config_entry_id || this._config.entity !== config.entity;
    this._config = { ...config };
    if (!this._root) this._build();
    this._titleEl.textContent = this._config.title ?? this._t("title");
    if (changed && this._hass && this._loaded) this._load();
    this._renderChart();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      if (!this._root) this._build();
      this._titleEl.textContent = this._config.title ?? this._t("title");
      this._renderPanel();
      this._load();
    }
  }

  get hass() {
    return this._hass;
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  connectedCallback() {
    // Keep the "now" line moving.
    this._timer = setInterval(() => this._renderChart(), 60_000);
    if (this._ro && this._chartEl) this._ro.observe(this._chartEl);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._ro?.disconnect();
  }

  // ---------------------------------------------------------------- helpers

  _t(key, vars = {}) {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").slice(0, 2);
    const text = (STRINGS[lang] || STRINGS.en)[key] ?? STRINGS.en[key] ?? key;
    return text.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
  }

  get _dirty() {
    return JSON.stringify(this._points) !== this._orig;
  }

  _entryId() {
    if (this._config.config_entry_id) return this._config.config_entry_id;
    const ent = this._config.entity && this._hass?.entities?.[this._config.entity];
    const dev = ent?.device_id && this._hass?.devices?.[ent.device_id];
    return ent?.config_entry_id || dev?.primary_config_entry || dev?.config_entries?.[0];
  }

  async _call(service, data = {}, returnResponse = false) {
    const entry = this._entryId();
    const msg = {
      type: "call_service",
      domain: DOMAIN,
      service,
      service_data: entry ? { config_entry_id: entry, ...data } : data,
    };
    if (returnResponse) msg.return_response = true;
    const res = await this._hass.callWS(msg);
    return res?.response;
  }

  // ---------------------------------------------------------------- device I/O

  async _load() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._renderPanel();
    try {
      const res = await this._call("get_schedule", {}, true);
      const colors = res.colors || [];
      this._series = res.channels.map((name, i) => this._mkSeries(name, colors[i] || FALLBACK_COLORS[i]));
      this._hasFan = !!res.fan;
      if (res.fan) this._series.push(this._mkSeries(res.fan.name || "Fan", res.fan.color || FALLBACK_COLORS[8]));
      this._max = res.max_points || 16;
      this._points = res.points.map((p) => ({
        t: parseTime(p.time),
        v: [...p.levels.map(Number), ...(res.fan ? [Number(p.fan ?? 0)] : [])],
      }));
      this._points.sort((a, b) => a.t - b.t);
      this._orig = JSON.stringify(this._points);
      this._loaded = true;
      this._sel = null;
      this._cursor = null;
      if (this._focus !== null && this._focus >= this._series.length) this._focus = null;
      if (this._msg?.kind === "error") this._msg = null;
    } catch (err) {
      this._msg = { kind: "error", text: err?.message || String(err) };
    } finally {
      this._loading = false;
      this._renderAll();
    }
  }

  _mkSeries(name, color) {
    return { name: String(name).trim(), color, light: luminance(color) > 0.6 };
  }

  async _save() {
    if (this._saving || !this._loaded) return;
    this._saving = true;
    this._msg = null;
    this._renderPanel();
    const n = this._channelCount();
    const points = this._points.map((p) => {
      const out = { time: fmt(p.t), levels: p.v.slice(0, n) };
      if (this._hasFan) out.fan = p.v[n];
      return out;
    });
    try {
      await this._call("set_schedule", { points });
      this._saving = false;
      await this._load(); // read back what the controller actually stored
      this._msg = { kind: "ok", text: this._t("saved") };
    } catch (err) {
      this._msg = { kind: "error", text: err?.message || String(err) };
    } finally {
      this._saving = false;
      this._renderAll();
    }
  }

  _channelCount() {
    return this._series.length - (this._hasFan ? 1 : 0);
  }

  /** Download what the editor shows, in the controller's preset format. */
  _backup() {
    const csv = scheduleToCsv(this._points, this._channelCount(), this._hasFan);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `rival-aqua-schedule-${new Date().toISOString().slice(0, 10)}.csv`;
    this.shadowRoot.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
  }

  /** Load a preset CSV into the editor as unsaved changes; nothing is sent until Save. */
  async _restore(file) {
    try {
      if (file.size > 64 * 1024) throw new Error("file too large");
      const points = csvToSchedule(await file.text(), this._channelCount(), this._hasFan, this._max);
      this._points = points;
      this._sel = null;
      this._cursor = null;
      this._msg = { kind: "ok", text: this._t("restored", { n: points.length, file: file.name }) };
    } catch (err) {
      this._msg = { kind: "error", text: this._t("badFile", { why: err.message }) };
    }
    this._renderAll();
  }

  // ---------------------------------------------------------------- editing

  _select(i) {
    this._sel = i;
    this._cursor = null;
    this._renderAll();
  }

  _addPoint(t) {
    if (this._points.length >= this._max) {
      this._msg = { kind: "error", text: this._t("full", { n: this._max }) };
      this._renderPanel();
      return;
    }
    t = clamp(Math.round(t), 1, DAY - 1);
    if (this._points.some((p) => p.t === t)) {
      this._msg = { kind: "error", text: this._t("taken", { t: fmt(t) }) };
      this._renderPanel();
      return;
    }
    const p = { t, v: this._series.map((_, s) => interpolate(this._points, s, t)) };
    this._points.push(p);
    this._points.sort((a, b) => a.t - b.t);
    this._msg = null;
    this._select(this._points.indexOf(p));
  }

  _deletePoint(i) {
    if (i === null || !this._points[i]) return;
    if (this._points.length <= 1) {
      this._msg = { kind: "error", text: this._t("lastPoint") };
      this._renderPanel();
      return;
    }
    this._points.splice(i, 1);
    this._msg = null;
    this._select(this._points.length ? Math.min(i, this._points.length - 1) : null);
  }

  /** Move point i to minute t, kept strictly between its neighbours. Returns the time used. */
  _moveTo(i, t) {
    const lo = i > 0 ? this._points[i - 1].t + 1 : 1;
    const hi = i < this._points.length - 1 ? this._points[i + 1].t - 1 : DAY - 1;
    this._points[i].t = clamp(Math.round(t), lo, hi);
    return this._points[i].t;
  }

  _setLevel(i, s, v) {
    this._points[i].v[s] = clamp(Math.round(v), 0, 100);
  }

  // ---------------------------------------------------------------- DOM

  _build() {
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <div class="title"></div>
          <button class="icon" data-act="backup" aria-label="backup">
            <svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M5 20h14v-2H5zm7-3 5-5h-3V4h-4v8H7z"/></svg>
          </button>
          <button class="icon" data-act="restore" aria-label="restore">
            <svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M5 20h14v-2H5zm7-16-5 5h3v6h4V9h3z"/></svg>
          </button>
          <input type="file" accept=".csv,text/csv,text/plain" hidden>
          <button class="icon" data-act="reload" aria-label="reload">
            <svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M17.65 6.35A7.96 7.96 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z"/></svg>
          </button>
        </div>
        <div class="chips"></div>
        <div class="chart"><svg class="plot" role="img"></svg></div>
        <div class="panel"></div>
        <div class="footer"></div>
      </ha-card>`;
    const root = this.shadowRoot;
    this._root = root.querySelector("ha-card");
    this._titleEl = root.querySelector(".title");
    this._chipsEl = root.querySelector(".chips");
    this._chartEl = root.querySelector(".chart");
    this._svg = root.querySelector("svg.plot");
    this._panelEl = root.querySelector(".panel");
    this._footerEl = root.querySelector(".footer");
    this._fileEl = root.querySelector('input[type="file"]');
    this._fileEl.addEventListener("change", () => {
      const file = this._fileEl.files?.[0];
      this._fileEl.value = "";
      if (file) this._restore(file);
    });
    this._root.tabIndex = 0;

    this._ro = new ResizeObserver(() => {
      const w = Math.round(this._chartEl.clientWidth);
      if (w && w !== this._width) {
        this._width = w;
        this._renderChart();
      }
    });
    this._ro.observe(this._chartEl);

    this._svg.addEventListener("pointerdown", (e) => this._onDown(e));
    this._svg.addEventListener("pointermove", (e) => this._onMove(e));
    this._svg.addEventListener("pointerup", (e) => this._onUp(e));
    this._svg.addEventListener("pointercancel", (e) => this._onUp(e));
    this._root.addEventListener("click", (e) => this._onClick(e));
    this._root.addEventListener("input", (e) => this._onInput(e));
    this._root.addEventListener("change", (e) => this._onChange(e));
    this._root.addEventListener("keydown", (e) => this._onKey(e));
  }

  _renderAll() {
    this._renderChips();
    this._renderChart();
    this._renderPanel();
  }

  _renderChips() {
    if (!this._chipsEl) return;
    const chip = (i, label, color) => `
      <button class="chip" data-focus="${i}" aria-pressed="${this._focus === i}">
        ${color ? `<span class="dot" style="background:${esc(color)}"></span>` : ""}${esc(label)}
      </button>`;
    this._chipsEl.innerHTML =
      this._series.length > 1
        ? chip("", this._t("all"), null).replace('aria-pressed="false"', `aria-pressed="${this._focus === null}"`) +
          this._series.map((s, i) => chip(i, s.name, s.color)).join("")
        : "";
  }

  // geometry
  _geom() {
    const w = this._width || 600;
    const h = Number(this._config.height) || 280;
    const g = { w, h, pl: 34, pr: 12, pt: 12, pb: 24 };
    g.pw = w - g.pl - g.pr;
    g.ph = h - g.pt - g.pb;
    return g;
  }
  _tToX(t, g = this._geom()) {
    return g.pl + (t / DAY) * g.pw;
  }
  _vToY(v, g = this._geom()) {
    return g.pt + (1 - v / 100) * g.ph;
  }
  _xToT(x, g = this._geom()) {
    return ((x - g.pl) / g.pw) * DAY;
  }
  _snap(t, fine) {
    const step = fine ? 1 : SNAP;
    return clamp(Math.round(t / step) * step, 1, DAY - 1);
  }
  _local(e) {
    const r = this._svg.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  /** Draw order: the focused series last (on top). */
  _order() {
    const idx = this._series.map((_, i) => i);
    return this._focus === null ? idx : [...idx.filter((i) => i !== this._focus), this._focus];
  }

  _renderChart() {
    if (!this._svg) return;
    const g = this._geom();
    const X = (t) => this._tToX(t, g).toFixed(1);
    const Y = (v) => this._vToY(v, g).toFixed(1);
    let o = "";

    // grid
    for (const v of [0, 25, 50, 75, 100]) {
      o += `<line class="grid" x1="${g.pl}" x2="${g.w - g.pr}" y1="${Y(v)}" y2="${Y(v)}"/>`;
      o += `<text x="${g.pl - 6}" y="${+Y(v) + 4}" text-anchor="end">${v}</text>`;
    }
    const labelEvery = g.w < 420 ? 6 : g.w < 720 ? 3 : 2;
    for (let hr = 0; hr <= 24; hr++) {
      const major = hr % labelEvery === 0;
      o += `<line class="${major ? "grid" : "grid minor"}" x1="${X(hr * 60)}" x2="${X(hr * 60)}" y1="${g.pt}" y2="${g.h - g.pb}"/>`;
      if (major) o += `<text x="${X(hr * 60)}" y="${g.h - 6}" text-anchor="middle">${String(hr).padStart(2, "0")}</text>`;
    }

    // now
    const now = new Date();
    const nowT = now.getHours() * 60 + now.getMinutes();
    o += `<line class="now" x1="${X(nowT)}" x2="${X(nowT)}" y1="${g.pt}" y2="${g.h - g.pb}"/>`;

    // selection / cursor
    if (this._sel !== null && this._points[this._sel]) {
      const x = X(this._points[this._sel].t);
      o += `<line class="sel" x1="${x}" x2="${x}" y1="${g.pt}" y2="${g.h - g.pb}"/>`;
      o += `<text class="sel-label" x="${x}" y="${g.pt + 10}" text-anchor="middle">${fmt(this._points[this._sel].t)}</text>`;
    }
    if (this._cursor !== null) {
      const x = X(this._cursor);
      o += `<line class="cursor" x1="${x}" x2="${x}" y1="${g.pt}" y2="${g.h - g.pb}"/>`;
    }

    // curves
    const order = this._order();
    for (const s of order) {
      const ser = this._series[s];
      const dim = this._focus !== null && this._focus !== s;
      const pts = [`${X(0)},${Y(0)}`, ...this._points.map((p) => `${X(p.t)},${Y(p.v[s])}`), `${X(DAY)},${Y(0)}`].join(" ");
      if (ser.light) o += `<polyline class="halo${dim ? " dim" : ""}" points="${pts}"/>`;
      o += `<polyline class="curve${dim ? " dim" : ""}" points="${pts}" style="stroke:${esc(ser.color)}"/>`;
    }

    // markers (dimmed series are not editable)
    for (const s of order) {
      if (this._focus !== null && this._focus !== s) continue;
      const ser = this._series[s];
      this._points.forEach((p, i) => {
        const sel = i === this._sel;
        o += `<circle class="marker${ser.light ? " light" : ""}${sel ? " selected" : ""}" cx="${X(p.t)}" cy="${Y(p.v[s])}" r="${sel ? 6 : 4.5}" style="fill:${esc(ser.color)}"/>`;
      });
    }

    this._svg.setAttribute("width", g.w);
    this._svg.setAttribute("height", g.h);
    this._svg.setAttribute("viewBox", `0 0 ${g.w} ${g.h}`);
    this._svg.innerHTML = o;
  }

  _renderPanel() {
    if (!this._panelEl) return;
    const busy = this._loading || this._saving;
    let html = "";

    if (!this._loaded) {
      html = this._loading ? `<div class="hint">${this._t("loading")}</div>` : "";
    } else if (this._sel !== null && this._points[this._sel]) {
      const i = this._sel;
      const p = this._points[i];
      html = `
        <div class="row head">
          <button class="icon" data-act="prev" aria-label="${this._t("prev")}" ${i === 0 ? "disabled" : ""}>‹</button>
          <span class="label">${this._t("point")} ${i + 1} ${this._t("of")} ${this._points.length}</span>
          <button class="icon" data-act="next" aria-label="${this._t("next")}" ${i === this._points.length - 1 ? "disabled" : ""}>›</button>
          <label class="time">${this._t("time")}
            <input type="time" step="60" data-field="time" value="${fmt(p.t)}" ${busy ? "disabled" : ""}>
          </label>
          <span class="grow"></span>
          <button class="btn danger" data-act="delete" ${busy || this._points.length <= 1 ? "disabled" : ""}>${this._t("delete")}</button>
        </div>
        ${this._series
          .map(
            (s, k) => `
          <div class="row level${this._focus !== null && this._focus !== k ? " dim" : ""}">
            <span class="dot" style="background:${esc(s.color)}"></span>
            <span class="name">${esc(s.name)}</span>
            <input type="range" min="0" max="100" step="1" data-level="${k}" value="${p.v[k]}" ${busy ? "disabled" : ""}>
            <input type="number" min="0" max="100" step="1" data-level="${k}" value="${p.v[k]}" ${busy ? "disabled" : ""}>
          </div>`,
          )
          .join("")}`;
    } else if (this._cursor !== null) {
      const t = this._cursor;
      const full = this._points.length >= this._max;
      html = `
        <div class="row head">
          <button class="btn primary" data-act="add" ${busy || full ? "disabled" : ""}>${this._t("add")} ${fmt(t)}</button>
          <span class="levels">${this._series
            .map((s, k) => `<span class="lv"><span class="dot" style="background:${esc(s.color)}"></span>${interpolate(this._points, k, t)}</span>`)
            .join("")}</span>
        </div>
        ${full ? `<div class="hint">${this._t("full", { n: this._max })}</div>` : ""}`;
    } else {
      html = `<div class="hint">${this._t("hint")}</div>`;
    }
    this._panelEl.innerHTML = html;
    this._renderFooter();
  }

  _renderFooter() {
    if (!this._footerEl) return;
    // Built once and updated in place: replacing the buttons would swallow a click that blurs an
    // input first (blur → change → re-render between mousedown and click).
    if (!this._footerEl.firstChild) {
      this._footerEl.innerHTML = `
        <div class="msg" hidden></div>
        <div class="row">
          <span class="status"></span>
          <span class="grow"></span>
          <button class="btn" data-act="revert"></button>
          <button class="btn primary" data-act="save"></button>
        </div>
        <div class="note" hidden></div>`;
    }
    const $ = (sel) => this._footerEl.querySelector(sel);
    const busy = this._loading || this._saving;
    const dirty = this._loaded && this._dirty;
    const msg = $(".msg");
    msg.hidden = !this._msg;
    msg.className = `msg ${this._msg?.kind || ""}`;
    msg.textContent = this._msg?.text || "";
    $(".status").innerHTML = `${this._loaded ? `${this._points.length}/${this._max} ${esc(this._t("points"))}` : ""}${
      dirty ? ` · <b>${esc(this._t("unsaved"))}</b>` : ""
    }`;
    const revert = $('[data-act="revert"]');
    revert.textContent = this._t("revert");
    revert.disabled = busy || !dirty;
    const save = $('[data-act="save"]');
    save.textContent = this._saving ? this._t("saving") : this._t("save");
    save.disabled = busy || !dirty;
    const note = $(".note");
    note.hidden = !dirty;
    note.textContent = this._t("saveNote");
    for (const act of ["reload", "backup", "restore"]) {
      const b = this._root.querySelector(`[data-act="${act}"]`);
      b.disabled = busy || (act !== "reload" && !this._loaded);
      b.title = this._t(act);
      b.setAttribute("aria-label", b.title);
    }
  }

  /** Update the selected point's inputs in place (keeps focus while dragging/typing). */
  _syncPanel(skip) {
    const p = this._points[this._sel];
    if (!p) return;
    for (const el of this._panelEl.querySelectorAll("[data-level]")) {
      if (el !== skip) el.value = p.v[+el.dataset.level];
    }
    const time = this._panelEl.querySelector('[data-field="time"]');
    if (time && time !== skip) time.value = fmt(p.t);
    const label = this._panelEl.querySelector(".label");
    if (label) label.textContent = `${this._t("point")} ${this._sel + 1} ${this._t("of")} ${this._points.length}`;
    const prev = this._panelEl.querySelector('[data-act="prev"]');
    if (prev) prev.disabled = this._sel === 0;
    const next = this._panelEl.querySelector('[data-act="next"]');
    if (next) next.disabled = this._sel === this._points.length - 1;
    this._renderFooter();
  }

  // ---------------------------------------------------------------- pointer

  /** The marker or point column under the pointer: {p, s} (s null = column) or null. */
  _hit(e) {
    const { x, y } = this._local(e);
    const g = this._geom();
    const radius = e.pointerType === "touch" ? 22 : 12;
    let best = null;
    let bestD = Infinity;
    for (const s of this._order()) {
      if (this._focus !== null && this._focus !== s) continue;
      this._points.forEach((pt, p) => {
        const d = Math.hypot(this._tToX(pt.t, g) - x, this._vToY(pt.v[s], g) - y);
        // <= so later (focused / on-top) series win ties
        if (d <= radius && d <= bestD) {
          bestD = d;
          best = { p, s };
        }
      });
    }
    if (best) return best;
    for (let p = 0; p < this._points.length; p++) {
      if (Math.abs(this._tToX(this._points[p].t, g) - x) <= radius / 2) return { p, s: null };
    }
    return null;
  }

  _onDown(e) {
    if (!this._loaded || this._saving || e.button > 0) return;
    const hit = this._hit(e);
    const { x, y } = this._local(e);
    if (!hit) {
      // Empty space: remember the time so "Add point" can use it; a second tap there adds it.
      // (Own double-tap detection: the redraw replaces the elements under the pointer, so the
      // browser's dblclick is unreliable, and it never fires for touch.)
      const t = this._snap(this._xToT(x), e.shiftKey);
      const last = this._lastTap;
      this._lastTap = { x, y, at: e.timeStamp };
      if (last && e.timeStamp - last.at < 450 && Math.hypot(x - last.x, y - last.y) < 12) {
        this._lastTap = null;
        this._addPoint(t);
        return;
      }
      this._sel = null;
      this._cursor = t;
      this._msg = null;
      this._renderAll();
      return;
    }
    this._lastTap = null;
    e.preventDefault();
    this._svg.setPointerCapture(e.pointerId);
    const pt = this._points[hit.p];
    this._drag = { ...hit, x, y, t: pt.t, v: hit.s === null ? null : pt.v[hit.s], axis: hit.s === null ? "x" : null, moved: false };
    if (this._sel !== hit.p || this._cursor !== null) {
      this._msg = null;
      this._select(hit.p);
    }
    this._root.focus({ preventScroll: true });
  }

  _onMove(e) {
    const d = this._drag;
    if (!d) return;
    const { x, y } = this._local(e);
    const dx = x - d.x;
    const dy = y - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 5) return;
    d.moved = true;
    // Lock to the dominant direction so adjusting a level doesn't nudge the time and vice versa.
    if (!d.axis) d.axis = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
    const g = this._geom();
    if (d.axis === "x") {
      this._moveTo(d.p, this._snap(d.t + (dx / g.pw) * DAY, e.shiftKey));
    } else {
      this._setLevel(d.p, d.s, d.v - (dy / g.ph) * 100);
    }
    this._renderChart();
    this._syncPanel();
  }

  _onUp(e) {
    if (!this._drag) return;
    if (this._svg.hasPointerCapture?.(e.pointerId)) this._svg.releasePointerCapture(e.pointerId);
    this._drag = null;
  }

  // ---------------------------------------------------------------- panel events

  _onClick(e) {
    const btn = e.target.closest("button");
    if (!btn || btn.disabled) return;
    if (btn.dataset.focus !== undefined) {
      const f = btn.dataset.focus === "" ? null : +btn.dataset.focus;
      this._focus = this._focus === f ? null : f;
      this._renderAll();
      return;
    }
    switch (btn.dataset.act) {
      case "save":
        this._save();
        break;
      case "revert":
        this._points = JSON.parse(this._orig);
        this._sel = null;
        this._cursor = null;
        this._msg = null;
        this._renderAll();
        break;
      case "reload":
        if (!this._dirty || confirm(this._t("discard"))) {
          this._msg = null;
          this._load();
        }
        break;
      case "add":
        this._addPoint(this._cursor);
        break;
      case "backup":
        this._backup();
        break;
      case "restore":
        this._fileEl.click();
        break;
      case "delete":
        this._deletePoint(this._sel);
        break;
      case "prev":
        this._select(Math.max(0, this._sel - 1));
        break;
      case "next":
        this._select(Math.min(this._points.length - 1, this._sel + 1));
        break;
    }
  }

  _onInput(e) {
    const el = e.target;
    if (el.dataset.level !== undefined && this._sel !== null) {
      if (el.value === "") return;
      this._setLevel(this._sel, +el.dataset.level, +el.value);
      this._renderChart();
      this._syncPanel(el);
    }
  }

  _onChange(e) {
    const el = e.target;
    if (el.dataset.level !== undefined) {
      this._syncPanel(); // normalise e.g. 120 → 100
    } else if (el.dataset.field === "time" && this._sel !== null) {
      const t = parseTime(el.value);
      const p = this._points[this._sel];
      if (t === null || t === 0) {
        el.value = fmt(p.t);
        return;
      }
      if (this._points.some((q) => q !== p && q.t === t)) {
        this._msg = { kind: "error", text: this._t("taken", { t: fmt(t) }) };
        el.value = fmt(p.t);
        this._renderFooter();
        return;
      }
      // Typing may jump past neighbours: re-sort and keep the same point selected. Updated in
      // place, not re-rendered, so a click that caused this change (by blurring) still lands.
      p.t = t;
      this._points.sort((a, b) => a.t - b.t);
      this._sel = this._points.indexOf(p);
      this._msg = null;
      this._renderChart();
      this._syncPanel();
    }
  }

  _onKey(e) {
    if (e.target !== this._root || !this._loaded || this._saving) return; // let inputs handle their own keys
    const i = this._sel;
    if (e.key === "Escape") {
      this._sel = null;
      this._cursor = null;
      this._renderAll();
    } else if (i === null) {
      return;
    } else if (e.key === "Delete" || e.key === "Backspace") {
      this._deletePoint(i);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      this._moveTo(i, this._points[i].t + (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 15 : 1));
    } else if ((e.key === "ArrowUp" || e.key === "ArrowDown") && this._focus !== null) {
      this._setLevel(i, this._focus, this._points[i].v[this._focus] + (e.key === "ArrowDown" ? -1 : 1) * (e.shiftKey ? 10 : 1));
    } else {
      return;
    }
    e.preventDefault();
    this._renderChart();
    this._syncPanel();
  }
}

const STYLE = `
  :host { display: block; }
  ha-card { padding: 12px 16px 16px; outline: none; color: var(--primary-text-color); }
  .header { display: flex; align-items: center; gap: 8px; }
  .title { flex: 1; font-size: var(--ha-card-header-font-size, 1.25em); line-height: 1.6; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 4px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 16px;
    border: 1px solid var(--divider-color); background: none; color: inherit; font: inherit; font-size: .85em; cursor: pointer; }
  .chip[aria-pressed="true"] { border-color: var(--primary-color); background: rgba(var(--rgb-primary-color, 3, 169, 244), .14); }
  .dot { display: inline-block; flex: none; width: 10px; height: 10px; border-radius: 50%;
    box-shadow: inset 0 0 0 1px rgba(127, 127, 127, .6); }
  .chart { width: 100%; user-select: none; -webkit-user-select: none; }
  svg.plot { display: block; touch-action: pan-y; cursor: crosshair; overflow: visible; }
  svg text { fill: var(--secondary-text-color); font-size: 11px; font-family: inherit; }
  svg.plot line, svg.plot text, .curve, .halo { pointer-events: none; }
  .grid { stroke: var(--divider-color); stroke-width: 1; }
  .grid.minor { opacity: .45; }
  .now { stroke: var(--accent-color, #ff9800); stroke-width: 1.5; stroke-dasharray: 3 3; }
  .sel { stroke: var(--primary-color); stroke-width: 1.5; opacity: .7; }
  text.sel-label { fill: var(--primary-color); font-weight: 600; }
  .cursor { stroke: var(--secondary-text-color); stroke-width: 1; stroke-dasharray: 4 4; }
  .curve { fill: none; stroke-width: 2.5; stroke-linejoin: round; }
  .halo { fill: none; stroke: rgba(0, 0, 0, .35); stroke-width: 4.5; stroke-linejoin: round; }
  .dim { opacity: .22; }
  .marker { stroke: var(--card-background-color, #fff); stroke-width: 1.5; cursor: grab; touch-action: none; }
  .marker.light { stroke: rgba(0, 0, 0, .55); }
  .marker.selected { stroke: var(--primary-color); stroke-width: 2.5; }
  .panel { min-height: 40px; margin-top: 8px; }
  .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .row.head { margin-bottom: 6px; }
  .row.level { flex-wrap: nowrap; padding: 2px 0; }
  .row.level.dim { opacity: .5; }
  .row.level .name { width: 92px; flex: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .92em; }
  .row.level input[type=range] { flex: 1; min-width: 60px; accent-color: var(--primary-color); }
  .row.level input[type=number] { width: 56px; }
  .label { font-weight: 500; }
  .time { display: inline-flex; align-items: center; gap: 6px; color: var(--secondary-text-color); font-size: .92em; }
  input[type=time], input[type=number] { font: inherit; padding: 4px 6px; border-radius: 6px;
    border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
  .grow { flex: 1; }
  .levels { display: inline-flex; flex-wrap: wrap; gap: 10px; color: var(--secondary-text-color); font-size: .9em; }
  .lv { display: inline-flex; align-items: center; gap: 4px; }
  .hint, .note { color: var(--secondary-text-color); font-size: .88em; line-height: 1.4; }
  .note { margin-top: 6px; }
  .footer { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--divider-color); }
  .status { color: var(--secondary-text-color); font-size: .9em; }
  .status b { color: var(--warning-color, #ff9800); font-weight: 500; }
  [hidden] { display: none !important; }
  .msg { margin-bottom: 8px; padding: 6px 10px; border-radius: 6px; font-size: .9em; }
  .msg.error { background: rgba(219, 68, 55, .12); color: var(--error-color, #db4437); }
  .msg.ok { background: rgba(67, 160, 71, .12); color: var(--success-color, #43a047); }
  .btn { font: inherit; font-size: .92em; font-weight: 500; padding: 6px 14px; border-radius: 18px; cursor: pointer;
    border: 1px solid var(--divider-color); background: none; color: var(--primary-color); }
  .btn.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn.danger { color: var(--error-color, #db4437); }
  .btn:disabled, .icon:disabled { opacity: .45; cursor: default; }
  .icon { display: inline-flex; align-items: center; justify-content: center; min-width: 32px; height: 32px; padding: 0 4px;
    border: none; border-radius: 50%; background: none; color: var(--secondary-text-color); font-size: 1.3em; cursor: pointer; }
  .icon:not(:disabled):hover, .btn:not(:disabled):hover { filter: brightness(1.1); background-color: rgba(127, 127, 127, .12); }
  .btn.primary:not(:disabled):hover { background-color: var(--primary-color); }
`;

if (!customElements.get("rival-aqua-schedule-card")) {
  customElements.define("rival-aqua-schedule-card", RivalAquaScheduleCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "rival-aqua-schedule-card",
    name: "Rival Aqua schedule",
    description: "Edit the daily light schedule of a Rival Aqua controller.",
    preview: false,
    documentationURL: "https://github.com/bilousviktor/ha-rival-aqua",
  });
  console.info(`%c RIVAL-AQUA-SCHEDULE-CARD %c ${CARD_VERSION} `, "background:#0288d1;color:#fff", "");
}

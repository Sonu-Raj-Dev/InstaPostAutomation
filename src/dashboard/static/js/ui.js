// Shared UI helpers: escaping templates, API, toasts, modals, formatting, SVG charts.

export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
export const raw = (s) => ({ __raw: String(s ?? "") });
/** Tagged template: interpolations are escaped unless wrapped in raw() or are arrays of raw. */
export function html(strings, ...vals) {
  return raw(strings.reduce((out, s, i) => out + s + (i < vals.length ? fmtVal(vals[i]) : ""), ""));
}
function fmtVal(v) {
  if (v == null || v === false) return "";
  if (Array.isArray(v)) return v.map(fmtVal).join("");
  if (typeof v === "object" && "__raw" in v) return v.__raw;
  return esc(v);
}
export function mount(el, tpl) {
  el.innerHTML = tpl.__raw ?? tpl;
  icons(el);
}
export const icon = (name, cls = "") => raw(`<i data-lucide="${name}" class="${cls}"></i>`);
export function icons(root = document) {
  if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" }, nameAttr: "data-lucide", root });
}

export async function api(path, opts = {}) {
  const init = { ...opts, headers: { ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}), ...opts.headers } };
  if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) init.body = JSON.stringify(opts.body);
  let res;
  try { res = await fetch(path, init); } catch (e) { throw new Error("Server unreachable — is the app running?"); }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    const msg = (data && (data.error || data.detail)) || `Request failed (${res.status})`;
    const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    err.fields = data && data.fields;
    throw err;
  }
  return data;
}

export function toast(msg, kind = "info", ms = 4200) {
  let box = $(".toasts");
  if (!box) { box = document.createElement("div"); box.className = "toasts"; box.setAttribute("role", "status"); document.body.append(box); }
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  const ic = { ok: "check-circle-2", err: "alert-triangle", info: "info" }[kind] || "info";
  mount(t, html`${icon(ic)}<div>${msg}</div>`);
  box.append(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; setTimeout(() => t.remove(), 300); }, ms);
  return t;
}

/** modal({title, body: html, actions:[{label, kind, value}], wide}) → Promise(value | null) */
export function modal({ title, body, actions = [{ label: "Close", value: null }], wide = false, onMount }) {
  return new Promise((resolve) => {
    const scrim = document.createElement("div");
    scrim.className = "scrim";
    mount(scrim, html`<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-label="${title}">
      <div class="modal-h"><h3>${title}</h3><button class="btn ghost sm icon" data-x aria-label="Close">${icon("x")}</button></div>
      <div class="modal-b">${body}</div>
      <div class="modal-f">${actions.map((a, i) => html`<button class="btn ${a.kind || ""}" data-i="${i}">${a.label}</button>`)}</div></div>`);
    const close = (v) => { scrim.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
    const onKey = (e) => { if (e.key === "Escape") close(null); };
    scrim.addEventListener("click", (e) => {
      if (e.target === scrim || e.target.closest("[data-x]")) return close(null);
      const b = e.target.closest("[data-i]");
      if (b) { const a = actions[+b.dataset.i]; close(typeof a.value === "function" ? a.value(scrim) : a.value); }
    });
    document.addEventListener("keydown", onKey);
    document.body.append(scrim);
    (scrim.querySelector(".modal-f .btn:last-child") || scrim).focus();
    onMount && onMount(scrim);
  });
}
export const confirmDialog = (title, text, label = "Confirm", kind = "primary") =>
  modal({ title, body: html`<p style="margin:0">${text}</p>`, actions: [{ label: "Cancel", value: false, kind: "ghost" }, { label, value: true, kind }] });

export async function busy(btn, fn) {
  const prev = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="spin"></i>${btn.textContent.trim() ? " " + esc(btn.textContent.trim()) : ""}`;
  icons(btn);
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = prev; }
}

// ---------------------------------------------------------------- formatting
export const num = (n) => (n == null || n === "" ? "—" : Number(n).toLocaleString("en-IN"));
export const compact = (n) => (n == null ? "—" : Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n));
export function parseTs(s) {
  if (!s) return null;
  if (typeof s === "number") return new Date(s * 1000);
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(s) ? s : s.replace(" ", "T") + "+05:30"); // DB timestamps are IST
}
export function rel(s) {
  const d = parseTs(s);
  if (!d || isNaN(d)) return "—";
  const diff = (Date.now() - d) / 1000, a = Math.abs(diff);
  const f = a < 60 ? "just now" : a < 3600 ? `${Math.round(a / 60)} min` : a < 86400 ? `${Math.round(a / 3600)} h` : `${Math.round(a / 86400)} d`;
  if (f === "just now") return f;
  return diff > 0 ? `${f} ago` : `in ${f}`;
}
export const ist = (s, opts = { dateStyle: "medium", timeStyle: "short" }) => {
  const d = parseTs(s);
  return d && !isNaN(d) ? d.toLocaleString("en-IN", { ...opts, timeZone: "Asia/Kolkata" }) : "—";
};
export const timeIST = (s) => ist(s, { hour: "2-digit", minute: "2-digit", hour12: false });

export const STATUS = {
  DRAFT: ["Draft", ""], PENDING_APPROVAL: ["Awaiting approval", "warn"], REJECTED: ["Rejected", "err"],
  PUBLISHING: ["Publishing…", "live"], PUBLISHED: ["Published", "ok"], PUBLISH_FAILED: ["Publish failed", "err"],
  VERIFIED: ["Verified", "ok"], UNVERIFIED: ["Unverified", "warn"], UNREACHABLE: ["Unreachable", "err"], RESTRICTED: ["Blocks bots", "warn"],
  RUNNING: ["Running", "live"], SUCCESS: ["Success", "ok"], FAILED: ["Failed", "err"],
  RESOURCE_SENT: ["Resource sent", "ok"], AWAITING_REPLY: ["Awaiting DM reply", "warn"], NOT_FOLLOWING: ["Not following", ""],
  MATCHED: ["Matched", "info"], SKIPPED_SELF: ["Your own comment", ""], AWAITING_TAP: ["Waiting for button tap", "warn"], AWAITING_FOLLOW: ["Waiting for follow", "warn"], LEGACY_PROCESSED: ["Handled (legacy)", ""],
};
export const badge = (s) => { const [l, k] = STATUS[s] || [s, ""]; return html`<span class="chip ${k}"><span class="dot"></span>${l}</span>`; };

// ---------------------------------------------------------------- charts (hand-rolled SVG)
export function lineChart(series, { h = 220, color = "#4C7DFF", label = (v) => compact(v) } = {}) {
  if (!series.length) return raw(`<div class="empty"><p>No data points in this range.</p></div>`);
  const w = 720, pad = { l: 44, r: 12, t: 12, b: 26 };
  const vals = series.map((p) => +p.value || 0), max = Math.max(...vals, 1), min = Math.min(...vals, 0);
  const x = (i) => pad.l + (i * (w - pad.l - pad.r)) / Math.max(series.length - 1, 1);
  const y = (v) => pad.t + (1 - (v - min) / (max - min || 1)) * (h - pad.t - pad.b);
  const pts = series.map((p, i) => [x(i), y(+p.value || 0)]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const len = Math.round(pts.reduce((a, p, i) => (i ? a + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) : 0), 0));
  const id = "g" + Math.random().toString(36).slice(2, 7);
  const ticks = [0, 0.5, 1].map((t) => min + t * (max - min));
  const step = Math.ceil(series.length / 6);
  return raw(`<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Line chart">
    <defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".28"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    ${ticks.map((t) => `<line class="gridline" x1="${pad.l}" x2="${w - pad.r}" y1="${y(t)}" y2="${y(t)}"/><text x="${pad.l - 8}" y="${y(t) + 3}" text-anchor="end">${esc(label(Math.round(t)))}</text>`).join("")}
    <path class="area" d="${d} L ${x(series.length - 1)} ${h - pad.b} L ${pad.l} ${h - pad.b} Z" fill="url(#${id})"/>
    <path class="ln" d="${d}" stroke="${color}" style="--len:${len}"/>
    ${series.map((p, i) => (i % step === 0 || i === series.length - 1 ? `<text x="${x(i)}" y="${h - 6}" text-anchor="middle">${esc(p.date.slice(5))}</text>` : "")).join("")}
    ${pts.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="2.5" fill="${color}"><title>${esc(series[i].date)}: ${num(series[i].value)}</title></circle>`).join("")}
  </svg>`);
}
export function barList(rows, fmt = num) {
  if (!rows.length) return raw(`<div class="empty"><p>Nothing to compare yet.</p></div>`);
  const max = Math.max(...rows.map((r) => r.value), 1);
  return html`<div class="bars">${rows.map((r) => html`<div class="b"><span class="muted" title="${r.label}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.label}</span><div><i style="width:${(100 * r.value) / max}%"></i></div><span class="mono" style="text-align:right">${fmt(r.value)}</span></div>`)}</div>`;
}
export const emptyState = (ic, title, text, action = "") =>
  html`<div class="empty"><div class="ico">${icon(ic)}</div><h4>${title}</h4><p>${text}</p>${action}</div>`;

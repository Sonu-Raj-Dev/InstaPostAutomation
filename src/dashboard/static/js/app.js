// Router, shell state and polling. Pages live in ./pages/*.js and export { title, eyebrow, render(view, app), destroy? }.
import { $, $$, api, emptyState, html, icon, icons, mount, toast } from "./ui.js";

const ROUTES = {
  command: () => import("./pages/command.js"),
  create: () => import("./pages/create.js"),
  posts: () => import("./pages/posts.js"),
  intelligence: () => import("./pages/intelligence.js"),
  creator: () => import("./pages/creator.js"),
  approval: () => import("./pages/approval.js"),
  automation: () => import("./pages/automation.js"),
  dm: () => import("./pages/dm.js"),
  analytics: () => import("./pages/analytics.js"),
  settings: () => import("./pages/settings.js"),
};
const ALIASES = { dashboard: "command", research: "intelligence", queue: "approval" }; // old tab hashes

const listeners = new Set();
export const app = {
  state: null,
  params: new URLSearchParams(),
  on(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  async refresh(opts = "") {
    try {
      this.state = await api("/api/state" + opts);
      renderShell();
      if (offline) { offline = false; route(); }
      listeners.forEach((fn) => { try { fn(this.state); } catch (e) { console.error(e); } });
    } catch (e) { console.warn(e); }
    schedule();
    return this.state;
  },
  go(route, params = {}) {
    const q = new URLSearchParams(params).toString();
    location.hash = route + (q ? "?" + q : "");
  },
  setActions(tpl) { mount($("#topActions"), tpl || ""); },
  /** wait for a job to finish, polling; resolves with the final job row */
  async waitJob(id, onTick) {
    for (;;) {
      const j = await api(`/api/jobs/${id}`);
      onTick && onTick(j);
      if (j.status !== "RUNNING") { this.refresh(); return j; }
      await new Promise((r) => setTimeout(r, 1200));
    }
  },
  async startJob(path, body, label) {
    const r = await api(path, { method: "POST", body: body || {} });
    if (!r.started) { toast(r.error || "Job already running", "info"); return r.job_id ? this.waitJob(r.job_id) : null; }
    toast(`${label} started`, "info", 2500);
    this.refresh();
    return this.waitJob(r.job_id);
  },
};

let timer = 0, offline = false;
function schedule() {
  clearTimeout(timer);
  const busy = app.state && app.state.running && app.state.running.length;
  timer = setTimeout(() => app.refresh(), document.hidden ? 60000 : offline ? 3000 : busy ? 2000 : 15000);
}
document.addEventListener("visibilitychange", () => !document.hidden && app.refresh());

function renderShell() {
  const s = app.state;
  if (!s) return;
  const p = $("#navPending");
  p.hidden = !s.counts.pending;
  p.textContent = s.counts.pending;
  const m = s.meta;
  mount($("#sysCard"), html`
    <div class="sys-row"><span>Mode</span><span class="chip ${s.mode === "AUTO" ? "live" : "info"}">${s.mode === "AUTO" ? "Auto" : "Review"}</span></div>
    <div class="sys-row"><span>Instagram</span>${m.token_valid
      ? html`<span class="chip ok" title="@${m.username}"><span class="dot"></span>@${m.username}</span>`
      : html`<a class="chip err" href="#settings" title="${m.error || ""}"><span class="dot"></span>Reconnect</a>`}</div>
    <div class="sys-row"><span>Jobs</span>${s.running.length ? html`<span class="chip live"><span class="dot"></span>${s.running[0].kind}</span>` : html`<span class="dim">Idle</span>`}</div>`);
}

// ---------------------------------------------------------------- router
let current = null, navToken = 0;
async function route() {
  const [nameRaw, qs] = location.hash.replace(/^#/, "").split("?");
  const name = ALIASES[nameRaw] || (ROUTES[nameRaw] ? nameRaw : "command");
  app.params = new URLSearchParams(qs || "");
  const token = ++navToken;
  $$("#nav a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + name));
  if ($("#nav .adv a.on")) $("#adv").open = true;
  document.body.classList.remove("nav-open");
  if (current && current.destroy) try { current.destroy(); } catch (e) { console.error(e); }
  current = null;
  const view = $("#view");
  view.classList.remove("view"); void view.offsetWidth; view.classList.add("view");
  mount(view, html`<div class="grid">${[1, 2, 3].map(() => html`<div class="skel" style="height:120px"></div>`)}</div>`);
  app.setActions("");
  try {
    const mod = await ROUTES[name]();
    if (token !== navToken) return;
    const page = mod.default;
    $("#pageTitle").textContent = page.title;
    $("#eyebrow span").textContent = page.eyebrow || "SONU AI LAB";
    document.title = `${page.title} — SONU AI LAB`;
    if (!app.state) await app.refresh();
    if (!app.state) {
      offline = true;
      $("#pageTitle").textContent = page.title;
      return mount(view, html`<div class="card"><div class="card-b">${emptyState("server-off", "Can't reach the SONU AI LAB server", "Start it with python src/dashboard/app.py — this page reconnects automatically.")}</div></div>`);
    }
    current = page;
    await page.render(view, app);
    icons(view);
  } catch (e) {
    console.error(e);
    mount(view, html`<div class="notice err">${icon("alert-triangle")}<div><b>This page failed to load.</b><br>${e.message}</div></div>`);
  }
}
window.addEventListener("hashchange", route);

// ---------------------------------------------------------------- login (cloud)
let loginShown = false;
window.addEventListener("auth-required", () => {
  if (loginShown) return;
  loginShown = true;
  const el = document.createElement("div");
  el.className = "scrim";
  el.style.background = "rgba(4,6,13,.97)";
  mount(el, html`<form class="modal" style="width:min(380px,100%)" id="loginForm">
    <div class="modal-h" style="justify-content:center;text-align:center;display:grid;gap:10px">
      <svg class="brand-mark" viewBox="0 0 34 34" style="width:44px;height:44px;margin:0 auto" aria-hidden="true"><use href="#mark"/></svg>
      <h3>SONU AI LAB</h3><p class="dim" style="margin:0;font-size:13px">Sign in to manage your Instagram automation</p></div>
    <div class="modal-b"><label class="field"><span>Password</span><input class="input" type="password" name="pw" autocomplete="current-password" required autofocus></label>
      <p class="err" id="loginErr" style="color:var(--err);font-size:12.5px;margin:8px 0 0"></p></div>
    <div class="modal-f"><button class="btn primary" style="width:100%" type="submit">Sign in</button></div></form>`);
  document.body.append(el);
  el.querySelector("input").focus();
  el.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/login", { method: "POST", body: { password: e.target.pw.value } }); location.reload(); }
    catch (err) { el.querySelector("#loginErr").textContent = err.message; }
  };
});
$("#navToggle").addEventListener("click", () => document.body.classList.toggle("nav-open"));
document.addEventListener("click", (e) => { if (document.body.classList.contains("nav-open") && !e.target.closest(".side, #navToggle")) document.body.classList.remove("nav-open"); });

window.addEventListener("DOMContentLoaded", () => icons());
app.refresh().then(route);

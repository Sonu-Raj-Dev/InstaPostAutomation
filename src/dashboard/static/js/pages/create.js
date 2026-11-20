// Create post — the simple 3-step flow: 1 Choose → 2 Review → 3 Publish.
import { $, $$, api, badge, busy, confirmDialog, emptyState, html, icon, mount, toast } from "../ui.js";

const W = 1080, H = 1350;
const STEPS = ["Choose", "Review", "Publish"];
let off = null;

export default {
  title: "Create post",
  eyebrow: "3 steps · research to Instagram",
  async render(view, app) {
    const id = +app.params.get("id") || 0;
    const step = id ? Math.max(2, +app.params.get("step") || 2) : 1;
    mount(view, html`<ol class="stepper">${STEPS.map((s, i) => html`<li class="${i + 1 < step ? "done" : i + 1 === step ? "on" : ""}"><b>${i + 1 < step ? icon("check") : i + 1}</b><span>${s}</span></li>`)}</ol><div id="stepBody"></div>`);
    const body = $("#stepBody");
    if (step === 1) return chooseStep(body, app);
    let c;
    try { c = await api(`/api/carousels/${id}`); } catch (e) { return mount(body, html`<div class="notice err">${icon("alert-triangle")}<div>${e.message}</div></div>`); }
    if (c.status === "PUBLISHED") return doneStep(body, app, c);
    return step === 2 ? reviewStep(body, app, c) : publishStep(body, app, c);
  },
  destroy() { off && off(); off = null; },
};

// ------------------------------------------------------------------ 1. choose
async function chooseStep(body, app) {
  let mode = "single", cat = "", picked = new Set();
  const all = (await api("/api/topics?status=NEW")).filter((t) => t.verification_status === "VERIFIED");
  const usable = (t) => mode === "single" || ["github", "hf"].includes(t.source_kind);
  const cats = [...new Set(all.map((t) => t.category))];
  const draw = () => {
    const rows = all.filter((t) => (!cat || t.category === cat) && usable(t)).sort((a, b) => b.opportunity_score - a.opportunity_score).slice(0, 12);
    mount(body, html`
      <div class="choose-head">
        <div><h2 class="h2">What do you want to post?</h2><p class="muted">Only verified stories from today's research are shown.</p></div>
        <div class="mode-pick">
          <button class="${mode === "single" ? "on" : ""}" data-mode="single">${icon("square")}<b>One tool</b><span>Deep dive on one thing</span></button>
          <button class="${mode === "pack" ? "on" : ""}" data-mode="pack">${icon("layout-grid")}<b>Pack of tools</b><span>“5 tools for…” — most saved format</span></button>
        </div></div>
      <div class="row" style="margin:6px 0 16px;gap:6px"><button class="chip ${!cat ? "info" : ""}" data-cat="">All</button>${cats.map((c) => html`<button class="chip ${cat === c ? "info" : ""}" data-cat="${c}">${c}</button>`)}</div>
      ${rows.length ? html`<div class="pick-grid">${rows.map((t) => html`<button class="pick ${picked.has(t.id) ? "on" : ""}" data-id="${t.id}">
          <div class="pick-img">${t.preview_image_url ? html`<img src="${t.preview_image_url}" alt="" loading="lazy" referrerpolicy="no-referrer">` : icon("image")}</div>
          <div class="pick-b"><b>${t.title.includes("/") && !t.title.includes(" ") ? t.title.split("/")[1] : t.title}</b><p>${(t.description || t.why_it_matters || "").slice(0, 110)}</p>
          <div class="row" style="gap:6px">${t.stars ? html`<span class="chip">${t.source_kind === "hn" ? "▲" : "★"} ${Number(t.stars).toLocaleString("en-IN")}</span>` : ""}<span class="chip">${t.category}</span></div></div>
          <i class="tick">${icon("check")}</i></button>`)}</div>`
        : emptyState("radar", "Nothing to post in this category yet", "Run research from Home and verified stories will appear here.", html`<a class="btn sm primary" href="#intelligence">Open research</a>`)}
      <div class="action-bar"><span class="muted">${mode === "pack" ? `${picked.size} selected · pick 2–8 tools` : picked.size ? "1 selected" : "Pick one"}</span>
        <button class="btn primary" id="go" ${(mode === "pack" ? picked.size >= 2 : picked.size === 1) ? "" : "disabled"}>${icon("sparkles")}Create post</button></div>`);
  };
  body.onclick = async (e) => {
    const m = e.target.closest("[data-mode]"), c = e.target.closest("[data-cat]"), p = e.target.closest(".pick"), go = e.target.closest("#go");
    if (m) { mode = m.dataset.mode; picked.clear(); if (mode === "pack") preselect(); draw(); }
    else if (c) { cat = c.dataset.cat; if (mode === "pack") { picked.clear(); preselect(); } draw(); }
    else if (p) {
      const id = +p.dataset.id;
      if (mode === "single") { picked = new Set([id]); }
      else picked.has(id) ? picked.delete(id) : picked.size < 8 ? picked.add(id) : toast("A pack holds up to 8 tools", "info");
      draw();
    } else if (go) {
      await busy(go, async () => {
        const wait = toast("Reading each README and checking real screenshots… this takes 10–40 seconds.", "info", 60000);
        try {
          const c = await api("/api/carousels", { method: "POST", body: mode === "pack" ? { topic_ids: [...picked] } : { topic_id: [...picked][0] } });
          wait.remove();
          app.go("create", { id: c.id, step: 2 });
        } catch (err) { wait.remove(); toast(err.message, "err"); }
      });
    }
  };
  function preselect() {
    all.filter((t) => (!cat || t.category === cat) && usable(t)).sort((a, b) => b.opportunity_score - a.opportunity_score).slice(0, 4).forEach((t) => picked.add(t.id));
  }
  draw();
}

// ------------------------------------------------------------------ 2. review
async function reviewStep(body, app, c) {
  let i = 0;
  const s = app.state.settings;
  const total = () => c.slide_data.slides.length;
  mount(body, html`<div class="review">
    <div class="card review-stage"><div class="phone" id="ph"><div class="ig-bar"><i></i><span>${(app.state.handle || "").replace("@", "")}</span></div>
      <div id="fb" style="overflow:hidden"><iframe id="fr" title="Slide preview"></iframe></div><div class="ig-dots" id="dots"></div></div>
      <div class="row" style="justify-content:center;margin-top:14px"><button class="btn icon" id="pv" aria-label="Previous slide">${icon("chevron-left")}</button><span class="mono" id="ct"></span><button class="btn icon" id="nx" aria-label="Next slide">${icon("chevron-right")}</button></div></div>
    <div class="stack" style="gap:16px">
      <div class="card"><div class="card-b stack" style="gap:14px">
        <h2 class="h2" style="margin:0">${c.headline}</h2>
        <div class="field"><span>Look</span><div class="seg" id="look"><button data-t="studio" class="${c.design.theme === "studio" ? "on" : ""}">Bright 3D</button><button data-t="midnight" class="${c.design.theme === "midnight" ? "on" : ""}">Dark</button><button data-t="signal" class="${c.design.theme === "signal" ? "on" : ""}">Violet</button></div></div>
        <label class="field"><span>Comment keyword <small>people comment this to get the guide</small></span><input class="input mono" id="kw" value="${c.cta_keyword}" maxlength="20"></label>
        <label class="field"><span>Caption</span><textarea class="textarea" id="cap" style="min-height:150px">${c.caption}</textarea></label>
        <a class="btn sm ghost" href="#creator?id=${c.id}" style="justify-self:start">${icon("pen-tool")}Edit slides in the advanced editor</a>
      </div></div>
      <div class="card"><div class="card-h"><h3>${icon("message-circle-heart")}What people get in their DM</h3></div><div class="card-b">
        <div class="chat">
          <div class="bub them">${s.dm_opener || ""}<span class="qr">Send me the access</span></div>
          <div class="bub me">Send me the access</div>
          ${s.dm_follow_gate === "1" ? html`<div class="bub them dim-b">${s.dm_not_following || ""}<span class="qr">I'm following ✅</span><small>only if they don't follow you yet</small></div>` : ""}
          <div class="bub them"><pre style="margin:0;white-space:pre-wrap;font:inherit">${c.resource_pack}</pre></div>
          <div class="bub them guide-bub"><div class="guide-frame"><div id="gin" style="position:relative;overflow:hidden"><iframe id="gf" title="Guide pages" src="/api/carousels/${c.id}/guide.html"></iframe></div></div><small>The full guide is sent as images like these</small></div>
        </div></div></div>
      <div class="action-bar" style="position:static"><button class="btn ghost" id="back">${icon("arrow-left")}Back</button><button class="btn primary" id="next">${icon("image-down")}Looks good — prepare to publish</button></div>
    </div></div>`);

  const fr = $("#fr");
  const show = () => {
    fr.src = `/api/carousels/${c.id}/slides/${i + 1}.html?t=${Date.now()}`;
    $("#ct").textContent = `${i + 1} / ${total()}`;
    mount($("#dots"), html`${c.slide_data.slides.map((_, k) => html`<b class="${k === i ? "on" : ""}"></b>`)}`);
    fit();
  };
  const fit = () => {
    const sc = Math.min(($(".review-stage").clientWidth - 40) / W, (innerHeight - 260) / H, 0.42);
    fr.style.cssText = `width:${W}px;height:${H}px;border:0;transform:scale(${sc});transform-origin:0 0;pointer-events:none`;
    $("#fb").style.cssText = `overflow:hidden;width:${W * sc}px;height:${H * sc}px`;
    $("#ph").style.width = W * sc + "px";
    const g = $("#gf"), gw = $(".guide-frame").clientWidth / W;
    const pages = (g.contentDocument && g.contentDocument.querySelectorAll(".g").length) || 2;
    g.style.cssText = `position:absolute;left:0;top:0;width:${W}px;height:${H * pages}px;border:0;transform:scale(${gw});transform-origin:0 0;pointer-events:none`;
    $("#gin").style.height = H * pages * gw + "px";
  };
  addEventListener("resize", fit);
  $("#gf").onload = fit;
  off = () => removeEventListener("resize", fit);
  $("#pv").onclick = () => { i = (i - 1 + total()) % total(); show(); };
  $("#nx").onclick = () => { i = (i + 1) % total(); show(); };
  $("#look").onclick = async (e) => {
    const b = e.target.closest("[data-t]");
    if (!b) return;
    $$("#look button").forEach((x) => x.classList.toggle("on", x === b));
    c = await api(`/api/carousels/${c.id}`, { method: "PUT", body: { design: { theme: b.dataset.t } } });
    show();
  };
  $("#kw").oninput = (e) => (e.target.value = e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ""));
  $("#back").onclick = () => app.go("create");
  $("#next").onclick = (e) => busy(e.currentTarget, async () => {
    try {
      const kw = $("#kw").value.trim();
      if (kw.length < 2) return toast("Pick a keyword with at least 2 letters", "err");
      const cap = $("#cap").value.replace(new RegExp(`Comment "${c.cta_keyword}"`, "g"), `Comment "${kw}"`);
      c = await api(`/api/carousels/${c.id}`, { method: "PUT", body: { cta_keyword: kw, caption: cap } });
      const t = toast("Rendering your slides and the DM guide (about 20 seconds)…", "info", 60000);
      const j = await app.startJob(`/api/carousels/${c.id}/render`, {}, "Render");
      t.remove();
      if (!j || j.status !== "SUCCESS") return toast(`Render failed: ${(j && j.error) || "unknown"}`, "err");
      if (c.status !== "PENDING_APPROVAL") await api(`/api/carousels/${c.id}/submit`, { method: "POST" });
      app.go("create", { id: c.id, step: 3 });
    } catch (err) { toast(err.message, "err"); }
  });
  show();
}

// ------------------------------------------------------------------ 3. publish
function publishStep(body, app, c) {
  const m = app.state.meta, s = app.state.settings, v = encodeURIComponent(c.rendered_at);
  const ready = !c.render_stale && c.rendered.length;
  mount(body, html`<div class="card"><div class="card-b stack" style="gap:20px">
    <h2 class="h2" style="margin:0">Ready to go live</h2>
    <div><div class="label">Post · ${c.rendered.length} slide${c.rendered.length > 1 ? "s" : ""}</div><div class="thumbs">${c.rendered.map((u) => html`<img src="${u}?v=${v}" alt="">`)}</div></div>
    <div><div class="label">DM guide · ${c.guide.length} page${c.guide.length > 1 ? "s" : ""}</div><div class="thumbs">${c.guide.map((u) => html`<img src="${u}?v=${v}" alt="">`)}</div></div>
    <ul class="checklist">
      <li class="${ready ? "ok" : "bad"}">${icon(ready ? "check-circle-2" : "x-circle")}Slides rendered at 1080×1350</li>
      <li class="${c.guide.length ? "ok" : "bad"}">${icon(c.guide.length ? "check-circle-2" : "x-circle")}DM guide ready (${c.guide.length} pages)</li>
      <li class="${m.token_valid ? "ok" : "bad"}">${icon(m.token_valid ? "check-circle-2" : "x-circle")}${m.token_valid ? html`Instagram connected as <b>@${m.username}</b>` : html`Instagram not connected — <a href="#settings">connect in Settings</a> (your post is saved and waiting)`}</li>
      <li class="ok">${icon("message-circle-heart")}<span>When someone comments <b class="mono">${c.cta_keyword}</b>, they automatically get the button flow and the guide
        <label class="row" style="gap:8px;margin-top:8px"><span class="switch"><input type="checkbox" id="auto" ${s.auto_dm === "1" ? "checked" : ""}><i></i></span>Auto-reply ${s.auto_dm === "1" ? "on" : "off"}</label></span></li>
    </ul>
    <div class="action-bar" style="position:static"><button class="btn ghost" id="back">${icon("arrow-left")}Back to review</button>
      <button class="btn publish" id="pub" ${ready && m.token_valid ? "" : "disabled"}>${icon("send")}Publish now${m.username ? ` to @${m.username}` : ""}</button></div>
    <div id="prog"></div></div></div>`);
  $("#back").onclick = () => app.go("create", { id: c.id, step: 2 });
  $("#auto").onchange = async (e) => {
    await api("/api/settings", { method: "POST", body: { auto_dm: e.target.checked ? "1" : "0" } });
    await app.refresh();
    toast(`Auto-reply ${e.target.checked ? "on" : "off"} for new posts`, "ok");
  };
  $("#pub").onclick = async (e) => {
    if (!(await confirmDialog("Publish now?", `This posts ${c.rendered.length} image${c.rendered.length > 1 ? "s" : ""} to @${m.username} right away and turns on auto-reply for “${c.cta_keyword}”.`, `Publish to @${m.username}`, "publish"))) return;
    busy(e.currentTarget, async () => {
      try {
        const r = await api(`/api/carousels/${c.id}/publish`, { method: "POST", body: { confirm: true } });
        if (!r.started) return toast(r.error, "err");
        const j = await app.waitJob(r.job_id, (jj) => mount($("#prog"), html`<div class="job"><div>${jj.stage || "Starting…"}</div><div class="progress"><i style="width:${jj.progress}%"></i></div></div>`));
        if (j.status === "SUCCESS") app.go("create", { id: c.id, step: 3 });
        else mount($("#prog"), html`<div class="notice err">${icon("alert-triangle")}<div><b>Publishing failed.</b><br>${j.error || JSON.parse(j.result_json || "{}").error}</div></div>`);
      } catch (err) { toast(err.message, "err"); }
    });
  };
}

function doneStep(body, app, c) {
  mount(body, html`<div class="card"><div class="card-b" style="text-align:center;padding:48px 20px">
    <div class="done-ico">${icon("check")}</div>
    <h2 class="h2">It's live on Instagram</h2>
    <p class="muted">Auto-reply is watching comments for <b class="mono">${c.cta_keyword}</b> and sends the guide by DM.</p>
    <div class="row" style="justify-content:center;margin-top:18px">${c.permalink ? html`<a class="btn primary" href="${c.permalink}" target="_blank" rel="noopener">${icon("external-link")}View post</a>` : ""}<a class="btn" href="#posts">${icon("list")}My posts</a><a class="btn" href="#create">${icon("plus")}Create another</a></div>
  </div></div>`);
}

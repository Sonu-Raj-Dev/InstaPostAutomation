import { $, $$, api, badge, busy, confirmDialog, emptyState, esc, html, icon, icons, modal, mount, rel, toast } from "../ui.js";

const LAYOUTS = { cover3d: "3D cover — real screenshots", showcase: "3D showcase — numbered", pack_cover: "Pack grid", features: "Feature list", cover: "Cover — headline + image", cover_type: "Cover — type only", single: "Single image post", point: "Statement", quote: "Pull quote",
  facts: "Fact tiles", facts_list: "Fact list", steps: "Steps / commands", image: "Screenshot", cta: "Call to action", cta_minimal: "CTA — minimal" };
const ROLE = { cover3d: "Hook", showcase: "Show it", pack_cover: "Hook", features: "Explain", cover: "Hook", cover_type: "Hook", single: "Hook + proof", point: "Explain", quote: "Emphasis", facts: "Proof", facts_list: "Proof", steps: "Activation", image: "Show it", cta: "Conversion", cta_minimal: "Conversion" };
const ACCENTS = ["#4C7DFF", "#8B5CF6", "#3BE0FF", "#FF4FD8", "#34D399", "#F5A524"];
const W = 1080, H = 1350;

let ctx = null; // per-mount state

function clone(o) { return JSON.parse(JSON.stringify(o)); }

export default {
  title: "Creator Studio",
  eyebrow: "Create · the post is the product",
  async render(view, app) {
    const id = +app.params.get("id") || 0;
    let c = null;
    if (id) {
      try { c = await api(`/api/carousels/${id}`); } catch (e) { toast(e.message, "err"); }
    } else {
      const all = await api("/api/carousels");
      c = all.find((x) => !x.legacy && !["PUBLISHED", "PUBLISHING"].includes(x.status)) || null;
    }
    if (!c) return renderPicker(view, app);
    if (c.legacy) return renderLegacy(view, app, c);
    ctx = { app, view, c, slides: clone(c.slide_data.slides), design: clone(c.design), sel: 0, zoom: "fit", dirty: false, docHead: "", sections: [], tab: "slide", ro: ["PUBLISHED", "PUBLISHING"].includes(c.status) };
    if (+app.params.get("slide")) ctx.sel = Math.min(+app.params.get("slide") - 1, ctx.slides.length - 1);
    layout();
    await refreshPreview();
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", fitStage);
    window.addEventListener("beforeunload", onUnload);
  },
  destroy() {
    if (!ctx) return;
    window.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", fitStage);
    window.removeEventListener("beforeunload", onUnload);
    if (ctx.dirty && !ctx.ro) save(true); // autosave on leave
    ctx = null;
  },
};

function onUnload(e) { if (ctx && ctx.dirty) { e.preventDefault(); e.returnValue = ""; } }
function onKey(e) {
  if (!ctx || e.target.closest("input, textarea, select, [contenteditable]")) return;
  if (e.key === "ArrowRight") select(Math.min(ctx.sel + 1, ctx.slides.length - 1));
  if (e.key === "ArrowLeft") select(Math.max(ctx.sel - 1, 0));
  if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
}

// ------------------------------------------------------------------ empty / legacy states
async function renderPicker(view, app) {
  const [cars, topics] = await Promise.all([api("/api/carousels"), api("/api/topics?status=NEW")]);
  const best = topics.filter((t) => t.verification_status === "VERIFIED").sort((a, b) => b.opportunity_score - a.opportunity_score).slice(0, 6);
  mount(view, html`<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr))">
    <div class="card"><div class="card-h"><h3>${icon("sparkles")}Start from a verified story</h3></div><div class="card-b stack">
      ${best.length ? best.map((t) => html`<button class="queue-item" data-topic="${t.id}"><div class="th">${t.preview_image_url ? html`<img src="${t.preview_image_url}" alt="" referrerpolicy="no-referrer">` : icon("file-text")}</div>
        <div><b>${t.title}</b><div class="dim" style="font-size:12px;margin-top:4px">${t.category} · score ${t.opportunity_score} · suggests ${t.suggested_format === "SINGLE" ? "single image" : t.suggested_slides + " slides"}</div></div></button>`)
        : emptyState("radar", "No verified stories", "Run research first — only verified stories can become posts.", html`<a class="btn sm primary" href="#intelligence">Daily Intelligence</a>`)}
    </div></div>
    <div class="card"><div class="card-h"><h3>${icon("archive")}Published & legacy posts</h3></div><div class="card-b stack">
      ${cars.length ? cars.map((x) => html`<a class="queue-item" href="#${x.legacy ? "approval" : "creator"}?id=${x.id}"><div class="th">${icon("image")}</div><div><b>${x.headline}</b><div class="row" style="margin-top:6px">${badge(x.status)}${x.legacy ? html`<span class="chip">legacy</span>` : ""}</div></div></a>`)
        : html`<p class="dim">Nothing yet.</p>`}
    </div></div></div>`);
  view.onclick = async (e) => {
    const b = e.target.closest("[data-topic]");
    if (!b) return;
    await busy(b, async () => {
      try { const c = await api("/api/carousels", { method: "POST", body: { topic_id: +b.dataset.topic } }); if (c.note) toast(c.note, "info"); app.go("creator", { id: c.id }); }
      catch (err) { toast(err.message, "err"); }
    });
  };
}

function renderLegacy(view, app, c) {
  mount(view, html`<div class="card" style="max-width:720px"><div class="card-b stack">
    <div class="notice warn">${icon("history")}<div><b>“${c.headline}” was created by the previous version.</b><br>It has no editable slide data (its slides were drawn directly to images with copy that wasn't tied to the research). Rebuild it from its research topic to edit it here.</div></div>
    <div class="row">${c.topic_id ? html`<button class="btn primary" id="rebuild">${icon("sparkles")}Rebuild from topic #${c.topic_id}</button>` : ""}<a class="btn" href="#creator">Back</a></div></div></div>`);
  const b = $("#rebuild");
  b && (b.onclick = () => busy(b, async () => {
    try { const n = await api("/api/carousels", { method: "POST", body: { topic_id: c.topic_id } }); app.go("creator", { id: n.id }); } catch (e) { toast(e.message, "err"); }
  }));
}

// ------------------------------------------------------------------ layout
function layout() {
  const { app, view, c } = ctx;
  const t = c.topic || {};
  const rec = c.slide_data.recommendation || {};
  app.setActions(html`<span id="statusChip">${badge(c.status)}</span>
    <button class="btn" id="aRegen" ${ctx.ro ? "disabled" : ""}>${icon("refresh-ccw")}Regenerate post</button>
    <button class="btn" id="aRender" ${ctx.ro ? "disabled" : ""}>${icon("image-down")}Render</button>
    <button class="btn" id="aSave" ${ctx.ro ? "disabled" : ""}>${icon("save")}Save draft</button>
    <button class="btn primary" id="aSubmit" ${ctx.ro || c.status === "PENDING_APPROVAL" ? "disabled" : ""}>${icon("send")}${c.status === "PENDING_APPROVAL" ? "In approval" : "Submit for approval"}</button>`);
  const counts = [1, 3, 5, 7, 10];
  const objectives = [...new Set(ctx.slides.map((s) => ROLE[s.layout]).filter(Boolean))];
  mount(view, html`<div class="studio">
    <aside class="panel card p-left"><div class="card-b">
      <div class="field"><span>Post</span><select class="select" id="switchPost"><option>${c.headline}</option></select></div>
      <div><div class="label">Selected story</div>
        <h3 style="font:600 16px/1.3 var(--f-display);margin:8px 0;overflow-wrap:anywhere"><a href="${t.url}" target="_blank" rel="noopener" style="color:var(--text)">${t.title}</a></h3>
        <div class="row">${badge(t.verification_status || "UNVERIFIED")}<span class="chip">${t.category}</span></div>
        <div class="dim" style="font-size:12px;margin-top:8px">${t.source} · published ${t.published_date || "—"}</div></div>
      <div><div class="label">Research summary</div><p class="muted" style="margin:6px 0 0;font-size:13px">${t.description || "—"}</p>
        ${t.why_it_matters ? html`<p style="margin:8px 0 0;font-size:13px">${t.why_it_matters}</p>` : ""}</div>
      <div><div class="label">Audience</div><p class="muted" style="margin:6px 0 0;font-size:13px">${t.target_audience || "—"}</p></div>
      <div><div class="label">Content objectives</div><div class="row" style="margin-top:8px">${objectives.map((o) => html`<span class="chip">${o}</span>`)}</div></div>
      <div><div class="label">Source material used</div>
        <ul class="muted" style="margin:6px 0 0;padding-left:16px;font-size:12.5px">${(t.facts || []).slice(0, 5).map((f) => html`<li>${f}</li>`)}
        ${(c.slide_data.install || []).length ? html`<li>${c.slide_data.install.length} install command(s) from README</li>` : html`<li class="dim">No install commands found in README</li>`}</ul></div>
      ${t.preview_image_url ? html`<div><div class="label">Visual reference</div><img src="${t.preview_image_url}" alt="Source preview" referrerpolicy="no-referrer" style="width:100%;border-radius:10px;margin-top:8px;border:1px solid var(--line)"><div class="dim" style="font-size:11.5px;margin-top:4px">Real preview image from the source</div></div>` : ""}
      <div><div class="label">Format</div>
        <p class="muted" style="font-size:12.5px;margin:6px 0 8px">${rec.reason || ""}</p>
        <div class="fmt-opts">${counts.map((n) => html`<button data-count="${n}" class="${n === rec.slides ? "rec" : ""} ${n === ctx.slides.length ? "on" : ""}" ${ctx.ro ? "disabled" : ""}><b>${n}</b>${n === 1 ? "single" : "slides"}</button>`)}</div>
        ${rec.format === "REEL" ? html`<div class="notice warn" style="margin-top:10px">${icon("clapperboard")}<div><b>Reel recommended.</b> A screen-recorded demo works best for this tool. This app can't record or edit video, so the carousel is the fallback.</div></div>` : ""}
      </div>
    </div></aside>

    <section class="stage">
      <div class="card stage-toolbar">
        <div class="row"><button class="btn sm icon" id="prev" aria-label="Previous slide">${icon("chevron-left")}</button><span class="mono" id="counter"></span><button class="btn sm icon" id="next" aria-label="Next slide">${icon("chevron-right")}</button></div>
        <div class="seg" id="zoom">${["fit", "50", "75", "100"].map((z) => html`<button data-z="${z}" class="${ctx.zoom === z ? "on" : ""}">${z === "fit" ? "Fit" : z + "%"}</button>`)}</div>
        <div class="row"><span class="dim" id="renderState" style="font-size:12px"></span><button class="btn sm" id="all">${icon("layout-grid")}Preview all</button></div>
      </div>
      <div class="canvas-wrap card" id="canvasWrap">
        <button class="nav-arrow l" id="pl" aria-label="Previous">${icon("chevron-left")}</button>
        <div class="phone" id="phone">
          <div class="ig-bar"><i></i><span>${(app.state.handle || "").replace("@", "")}</span><span class="dim" style="margin-left:auto;font-weight:500">4:5 · 1080×1350</span></div>
          <div id="frameBox" style="overflow:hidden"><iframe id="mainFrame" title="Slide preview" sandbox="allow-same-origin"></iframe></div>
          <div class="ig-dots" id="dots"></div>
        </div>
        <button class="nav-arrow r" id="pr" aria-label="Next">${icon("chevron-right")}</button>
      </div>
      <div class="strip" id="strip"></div>
      ${ctx.ro && c.permalink ? html`<div class="notice info">${icon("check-circle-2")}<div><b>Published.</b> <a href="${c.permalink}" target="_blank" rel="noopener">View on Instagram</a> — published posts are read-only.</div></div>` : ""}
    </section>

    <aside class="panel card"><div class="tabs" id="tabs" style="padding:0 10px">
        ${[["slide", "Slide"], ["design", "Design"], ["caption", "Caption"], ["quality", "Quality"]].map(([k, l]) => html`<button data-tab="${k}" class="${ctx.tab === k ? "on" : ""}">${l}</button>`)}
      </div><div class="card-b" id="inspector"></div></aside>
  </div>`);

  // post switcher (fill async)
  api("/api/carousels").then((all) => {
    const sel = $("#switchPost");
    if (!sel) return;
    mount(sel, html`${all.filter((x) => !x.legacy).map((x) => html`<option value="${x.id}" ${x.id === c.id ? "selected" : ""}>#${x.id} · ${x.headline.slice(0, 42)} (${x.status.toLowerCase().replace("_", " ")})</option>`)}`);
    sel.onchange = () => app.go("creator", { id: sel.value });
  });

  $("#prev").onclick = $("#pl").onclick = () => select(Math.max(ctx.sel - 1, 0));
  $("#next").onclick = $("#pr").onclick = () => select(Math.min(ctx.sel + 1, ctx.slides.length - 1));
  $("#zoom").onclick = (e) => { const b = e.target.closest("[data-z]"); if (b) { ctx.zoom = b.dataset.z; $$("#zoom button").forEach((x) => x.classList.toggle("on", x === b)); fitStage(); } };
  $("#tabs").onclick = (e) => { const b = e.target.closest("[data-tab]"); if (b) { ctx.tab = b.dataset.tab; $$("#tabs button").forEach((x) => x.classList.toggle("on", x === b)); inspector(); } };
  $("#all").onclick = previewAll;
  $(".fmt-opts").onclick = (e) => { const b = e.target.closest("[data-count]"); if (b && !ctx.ro) rebuild(+b.dataset.count); };
  $("#aSave").onclick = (e) => busy(e.currentTarget, () => save());
  $("#aRender").onclick = (e) => busy(e.currentTarget, () => renderNow());
  $("#aSubmit").onclick = (e) => busy(e.currentTarget, submit);
  $("#aRegen").onclick = async (e) => {
    if (!(await confirmDialog("Regenerate entire post?", "Slides and caption are rebuilt from the verified research. Your manual text edits on this post will be replaced.", "Regenerate", "primary"))) return;
    busy(e.currentTarget, () => rebuild(ctx.slides.length));
  };
  inspector();
  renderStatus();
}

// ------------------------------------------------------------------ preview engine
let previewTimer = 0;
function schedulePreview() { clearTimeout(previewTimer); previewTimer = setTimeout(refreshPreview, 180); }

async function refreshPreview() {
  if (!ctx) return;
  const doc = await api(`/api/carousels/${ctx.c.id}/preview`, { method: "POST", body: { slides: ctx.slides, design: ctx.design } });
  if (!ctx) return;
  const d = new DOMParser().parseFromString(doc, "text/html");
  ctx.docHead = d.head.innerHTML;
  ctx.sections = [...d.body.querySelectorAll("section")].map((s) => s.outerHTML);
  paintFrame($("#mainFrame"), ctx.sel);
  drawStrip();
  fitStage();
}

function paintFrame(frame, i) {
  if (!frame || !ctx.sections[i]) return;
  const body = ctx.sections[i];
  const doc = frame.contentDocument;
  if (frame.dataset.head === ctx.docHead && doc && doc.body && doc.readyState === "complete") {
    doc.body.innerHTML = body; // in-place patch: no reload, no flicker
  } else {
    frame.dataset.head = ctx.docHead;
    frame.srcdoc = `<!doctype html><html><head>${ctx.docHead}</head><body>${body}</body></html>`;
  }
  frame.style.width = W + "px";
  frame.style.height = H + "px";
}

function drawStrip() {
  const strip = $("#strip");
  if (!strip) return;
  if (strip.children.length !== ctx.slides.length) {
    mount(strip, html`${ctx.slides.map((s, i) => html`<button class="thumb-btn" data-i="${i}" aria-label="Slide ${i + 1}: ${LAYOUTS[s.layout] || s.layout}"><div class="frame-box"><iframe tabindex="-1" title="Slide ${i + 1} thumbnail" sandbox="allow-same-origin" style="transform:scale(${92 / W})"></iframe></div><span>${String(i + 1).padStart(2, "0")}</span></button>`)}
      ${ctx.ro ? "" : html`<button class="thumb-btn" id="addSlide" style="display:grid;place-items:center;height:117px;color:var(--text-3)" aria-label="Add slide" ${ctx.slides.length >= 10 ? "disabled" : ""}>${icon("plus")}</button>`}`);
    strip.onclick = (e) => {
      if (e.target.closest("#addSlide")) return addSlide();
      const b = e.target.closest("[data-i]");
      if (b) select(+b.dataset.i);
    };
  }
  $$("iframe", strip).forEach((f, i) => paintFrame(f, i));
  $$(".thumb-btn[data-i]", strip).forEach((b, i) => b.classList.toggle("on", i === ctx.sel));
  $("#counter").textContent = `${String(ctx.sel + 1).padStart(2, "0")} / ${String(ctx.slides.length).padStart(2, "0")}`;
  mount($("#dots"), html`${ctx.slides.map((_, i) => html`<b class="${i === ctx.sel ? "on" : ""}"></b>`)}`);
}

function fitStage() {
  if (!ctx) return;
  const wrap = $("#canvasWrap"), frame = $("#mainFrame"), box = $("#frameBox"), phone = $("#phone");
  if (!wrap || !frame) return;
  let s;
  if (ctx.zoom === "fit") {
    const availW = wrap.clientWidth - 110, availH = Math.max(window.innerHeight - 330, 380);
    s = Math.max(0.2, Math.min(availW / W, availH / H, 0.62));
  } else s = +ctx.zoom / 100;
  frame.style.transform = `scale(${s})`;
  box.style.width = W * s + "px";
  box.style.height = H * s + "px";
  phone.style.width = W * s + "px";
  wrap.style.overflow = s > 0.62 ? "auto" : "hidden";
  wrap.style.placeItems = s > 0.62 ? "start" : "center";
}

function select(i) {
  if (!ctx || i === ctx.sel && $("#mainFrame").srcdoc) { inspector(); return; }
  ctx.sel = i;
  paintFrame($("#mainFrame"), i);
  drawStrip();
  inspector();
  const b = $(`.thumb-btn[data-i="${i}"]`);
  b && b.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
}

function markDirty() {
  ctx.dirty = true;
  const b = $("#aSave");
  if (b) { b.classList.add("primary"); b.innerHTML = `<i data-lucide="save"></i>Save draft •`; icons(b); }
  renderStatus();
}

function renderStatus() {
  const el = $("#renderState");
  if (!el) return;
  const c = ctx.c;
  el.textContent = ctx.dirty ? "Unsaved changes" : c.render_stale ? (c.rendered.length ? "Render out of date" : "Not rendered yet") : `Rendered ${rel(c.rendered_at)}`;
  el.style.color = ctx.dirty || c.render_stale ? "var(--warn)" : "var(--ok)";
}

// ------------------------------------------------------------------ inspector
function inspector() {
  const el = $("#inspector");
  if (!el) return;
  const dis = ctx.ro ? "disabled" : "";
  const s = ctx.slides[ctx.sel];
  if (ctx.tab === "slide") {
    const list = (key, label, hint) => html`<div class="field"><span>${label}<small>${hint}</small></span><div class="bullets-edit" data-list="${key}">
      ${(s[key] || []).map((v, i) => html`<div class="row"><input class="input ${key === "steps" ? "mono" : ""}" data-li="${i}" value="${v}" ${dis}><button class="btn sm icon ghost" data-del="${i}" aria-label="Remove" ${dis}>${icon("x")}</button></div>`)}
      <button class="btn sm ghost" data-add="${key}" ${dis} style="justify-self:start">${icon("plus")}Add</button></div></div>`;
    const showTitle = !["quote", "cta", "cta_minimal"].includes(s.layout);
    mount(el, html`<div class="stack" style="gap:14px">
      <div class="spread"><div class="label">Slide ${ctx.sel + 1} · ${ROLE[s.layout] || ""}</div>
        <div class="row" style="gap:4px"><button class="btn sm icon ghost" data-mv="-1" aria-label="Move left" ${dis}>${icon("arrow-left")}</button><button class="btn sm icon ghost" data-mv="1" aria-label="Move right" ${dis}>${icon("arrow-right")}</button>
        <button class="btn sm icon ghost" data-dup aria-label="Duplicate slide" ${dis}>${icon("copy")}</button><button class="btn sm icon ghost" data-rm aria-label="Delete slide" ${dis || ctx.slides.length <= 1 ? "disabled" : ""}>${icon("trash-2")}</button></div></div>
      <label class="field"><span>Layout</span><select class="select" data-k="layout" ${dis}>${Object.entries(LAYOUTS).map(([k, v]) => html`<option value="${k}" ${k === s.layout ? "selected" : ""}>${v}</option>`)}</select></label>
      <label class="field"><span>Kicker</span><input class="input" data-k="kicker" value="${s.kicker}" maxlength="40" ${dis}></label>
      ${showTitle ? html`<label class="field"><span>Title <span class="counter ${(s.title || "").length > 70 ? "over" : ""}" data-count-for="title">${(s.title || "").length}/70</span></span><textarea class="textarea" style="min-height:60px" data-k="title" ${dis}>${s.title}</textarea></label>` : ""}
      ${s.layout.startsWith("cta") ? html`<div class="notice info">${icon("at-sign")}<div>Keyword <b>${s.keyword}</b> comes from the Caption tab so caption, slide and DM campaign stay in sync.</div></div>` : ""}
      <label class="field"><span>Body <span class="counter" data-count-for="body">${(s.body || "").length}</span></span><textarea class="textarea" data-k="body" ${dis}>${s.body}</textarea></label>
      ${["facts", "facts_list", "single"].includes(s.layout) ? html`<div class="field"><span>Facts<small>value · label</small></span><div class="bullets-edit">
        ${(s.facts || []).map(([v, k], i) => html`<div class="row"><input class="input" style="flex:1" data-fact="${i}" data-part="0" value="${v}" ${dis}><input class="input" style="flex:1.3" data-fact="${i}" data-part="1" value="${k}" ${dis}><button class="btn sm icon ghost" data-delfact="${i}" aria-label="Remove fact" ${dis}>${icon("x")}</button></div>`)}
        <button class="btn sm ghost" data-addfact ${dis} style="justify-self:start">${icon("plus")}Add fact</button></div></div>` : ""}
      ${s.layout === "steps" ? list("steps", "Steps", "one command or step per line") : ""}
      ${s.layout === "features" ? list("features", "Features", "one per line, max 5") : ""}
      ${["cover3d", "showcase"].includes(s.layout) ? list("images", "Screenshots", "real image URLs, first is the main one") : ""}
      ${s.layout === "cta" ? list("items", "What they get", "max 3") : ""}
      ${["cover", "image", "point", "single"].includes(s.layout) ? html`<div class="field"><span>Image</span>
        ${s.image ? html`<img src="${s.image}" alt="" referrerpolicy="no-referrer" style="width:100%;border-radius:10px;border:1px solid var(--line)">` : html`<div class="dim" style="font-size:12.5px">No image on this slide.</div>`}
        <input class="input" data-k="image" placeholder="https://… (real screenshot or source image)" value="${s.image || ""}" ${dis}>
        <div class="row"><label class="btn sm" ${dis}>${icon("upload")}Replace image<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" id="imgUp" hidden ${dis}></label>
        ${ctx.c.topic.preview_image_url && s.image !== ctx.c.topic.preview_image_url ? html`<button class="btn sm ghost" data-useprev ${dis}>Use source preview</button>` : ""}
        ${s.image ? html`<button class="btn sm ghost" data-k-clear="image" ${dis}>Remove</button>` : ""}</div></div>` : ""}
      <hr class="sep"><button class="btn" id="regenSlide" ${dis}>${icon("refresh-cw")}Regenerate this slide</button>
      <p class="dim" style="font-size:11.5px;margin:0">Regenerating swaps to an alternate treatment of the same verified material — it never invents facts.</p>
    </div>`);
    bindSlideInspector(el);
  } else if (ctx.tab === "design") {
    const d = ctx.design;
    mount(el, html`<div class="stack" style="gap:16px">
      <div class="field"><span>Theme</span><div class="seg" data-dk="theme">${["studio", "midnight", "paper", "signal"].map((t) => html`<button data-v="${t}" class="${d.theme === t ? "on" : ""}" ${dis}>${t[0].toUpperCase() + t.slice(1)}</button>`)}</div></div>
      <div class="field"><span>Accent</span><div class="row">${ACCENTS.map((a) => html`<button class="btn sm icon" data-accent="${a}" aria-label="Accent ${a}" style="background:${a};border-color:${d.accent.toUpperCase() === a ? "#fff" : "transparent"}" ${dis}></button>`)}<input type="color" id="accent" value="${d.accent}" aria-label="Custom accent" ${dis}></div></div>
      <div class="field"><span>Headline typeface</span><div class="seg" data-dk="font">${[["grotesk", "Grotesk"], ["serif", "Editorial serif"], ["mono", "Mono"]].map(([v, l]) => html`<button data-v="${v}" class="${d.font === v ? "on" : ""}" ${dis}>${l}</button>`)}</div></div>
      <label class="field"><span>Title size <span class="mono">${Math.round(d.title_scale * 100)}%</span></span><input type="range" min="0.7" max="1.3" step="0.05" value="${d.title_scale}" id="scale" ${dis}></label>
      <label class="row" style="justify-content:space-between"><span class="muted">Show handle in footer</span><span class="switch"><input type="checkbox" id="handle" ${d.show_handle ? "checked" : ""} ${dis}><i></i></span></label>
      <p class="dim" style="font-size:12px;margin:0">Design applies to every slide so the post stays consistent. Contrast is fixed per theme to stay readable on phones.</p></div>`);
    el.onclick = (e) => {
      const seg = e.target.closest("[data-v]"), acc = e.target.closest("[data-accent]");
      if (seg) { ctx.design[seg.closest("[data-dk]").dataset.dk] = seg.dataset.v; inspector(); }
      else if (acc) { ctx.design.accent = acc.dataset.accent; inspector(); }
      else return;
      markDirty(); schedulePreview();
    };
    $("#accent").oninput = (e) => { ctx.design.accent = e.target.value.toUpperCase(); markDirty(); schedulePreview(); };
    $("#scale").oninput = (e) => { ctx.design.title_scale = +e.target.value; e.target.previousElementSibling.querySelector(".mono").textContent = Math.round(e.target.value * 100) + "%"; markDirty(); schedulePreview(); };
    $("#handle").onchange = (e) => { ctx.design.show_handle = e.target.checked; markDirty(); schedulePreview(); };
  } else if (ctx.tab === "caption") {
    const c = ctx.c;
    mount(el, html`<div class="stack" style="gap:14px">
      <label class="field"><span>Caption <span class="counter" id="capCount">${c.caption.length}/2200</span></span><textarea class="textarea" style="min-height:220px" data-f="caption" maxlength="2200" ${dis}>${c.caption}</textarea></label>
      <label class="field"><span>Hashtags <span class="counter" id="tagCount">${c.hashtags.split(/\s+/).filter(Boolean).length} tags</span></span><textarea class="textarea mono" style="min-height:60px" data-f="hashtags" ${dis}>${c.hashtags}</textarea><small>3–15 tags work best. Appended under the caption when publishing.</small></label>
      <label class="field"><span>Comment keyword (CTA)</span><input class="input mono" data-f="cta_keyword" value="${c.cta_keyword}" maxlength="20" ${dis}><small>Updates the CTA slide. Use the same keyword in a Comment-to-DM campaign.</small></label>
      <label class="field"><span>Resource package <small>sent by DM</small></span><textarea class="textarea mono" style="min-height:120px" data-f="resource_pack" ${dis}>${c.resource_pack}</textarea></label>
      <label class="field"><span>Internal headline</span><input class="input" data-f="headline" value="${c.headline}" ${dis}></label>
      <button class="btn sm" id="copyCap">${icon("copy")}Copy caption + hashtags</button></div>`);
    el.oninput = (e) => {
      const f = e.target.dataset.f;
      if (!f) return;
      ctx.c[f] = f === "cta_keyword" ? e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "") : e.target.value;
      if (f === "cta_keyword") { e.target.value = ctx.c.cta_keyword; ctx.slides.forEach((s) => s.layout.startsWith("cta") && (s.keyword = ctx.c.cta_keyword)); schedulePreview(); }
      $("#capCount").textContent = ctx.c.caption.length + "/2200";
      $("#tagCount").textContent = ctx.c.hashtags.split(/\s+/).filter(Boolean).length + " tags";
      markDirty();
    };
    $("#copyCap").onclick = () => navigator.clipboard.writeText(`${ctx.c.caption}\n\n${ctx.c.hashtags}`).then(() => toast("Caption copied", "ok"), () => toast("Clipboard blocked by the browser", "err"));
  } else {
    const q = ctx.c.qc || {}, p = q.score ?? ctx.c.quality_score ?? 0;
    const col = p >= (q.threshold || 85) ? "var(--ok)" : p >= 60 ? "var(--warn)" : "var(--err)";
    mount(el, html`<div class="stack" style="gap:14px">
      <div class="row" style="gap:14px"><div class="score-ring" style="--p:${p};--c:${col}"><b>${p}</b></div>
        <div><b style="font:600 15px var(--f-display)">${q.passed ? "Ready for approval" : "Below threshold"}</b><div class="dim" style="font-size:12.5px">Threshold ${q.threshold || 85} · ${ctx.dirty ? "save to re-score" : "scored on last save"}</div></div></div>
      <div class="checks">${(q.checks || []).map((k) => html`<div class="check ${k.pass ? "pass" : "fail"}">${icon(k.pass ? "check-circle-2" : "alert-circle")}<div>${k.name}<small>${k.detail}</small></div><span class="pts">${k.points}/${k.max}</span></div>`)}</div></div>`);
  }
}

function bindSlideInspector(el) {
  const s = () => ctx.slides[ctx.sel];
  el.oninput = (e) => {
    const t = e.target;
    if (t.dataset.k) {
      s()[t.dataset.k] = t.value;
      const cnt = el.querySelector(`[data-count-for="${t.dataset.k}"]`);
      if (cnt) { cnt.textContent = t.dataset.k === "title" ? `${t.value.length}/70` : t.value.length; cnt.classList.toggle("over", t.dataset.k === "title" && t.value.length > 70); }
    } else if (t.dataset.li != null) s()[t.closest("[data-list]").dataset.list][+t.dataset.li] = t.value;
    else if (t.dataset.fact != null) s().facts[+t.dataset.fact][+t.dataset.part] = t.value;
    else return;
    markDirty(); schedulePreview();
  };
  el.onchange = async (e) => {
    if (e.target.dataset.k === "layout") {
      const sl = s();
      if (["facts", "facts_list", "single"].includes(sl.layout) && !sl.facts) sl.facts = (ctx.c.topic.facts || []).slice(0, 4).map(splitFact);
      if (sl.layout === "steps" && !sl.steps) sl.steps = (ctx.c.slide_data.install || []).slice(0, 4);
      if (sl.layout.startsWith("cta")) { sl.keyword = ctx.c.cta_keyword; sl.items = sl.items || ["Direct source link"]; }
      inspector(); markDirty(); schedulePreview();
    }
    if (e.target.id === "imgUp" && e.target.files[0]) {
      if (ctx.dirty) await save(true);
      const fd = new FormData();
      fd.append("file", e.target.files[0]);
      try {
        const c = await api(`/api/carousels/${ctx.c.id}/slides/${ctx.sel + 1}/image`, { method: "POST", body: fd });
        adopt(c); toast("Image replaced", "ok");
      } catch (err) { toast(err.message, "err"); }
    }
  };
  el.onclick = async (e) => {
    const b = e.target.closest("button");
    if (!b || b.disabled) return;
    const sl = s();
    if (b.dataset.add) { (sl[b.dataset.add] = sl[b.dataset.add] || []).push(""); }
    else if (b.dataset.del != null) sl[b.closest("[data-list]").dataset.list].splice(+b.dataset.del, 1);
    else if (b.hasAttribute("data-addfact")) (sl.facts = sl.facts || []).push(["", ""]);
    else if (b.dataset.delfact != null) sl.facts.splice(+b.dataset.delfact, 1);
    else if (b.dataset.kClear) sl[b.dataset.kClear] = "";
    else if (b.hasAttribute("data-useprev")) sl.image = ctx.c.topic.preview_image_url;
    else if (b.dataset.mv) {
      const j = ctx.sel + +b.dataset.mv;
      if (j < 0 || j >= ctx.slides.length) return;
      [ctx.slides[ctx.sel], ctx.slides[j]] = [ctx.slides[j], ctx.slides[ctx.sel]];
      ctx.sel = j; $("#strip").innerHTML = "";
    } else if (b.hasAttribute("data-dup")) {
      if (ctx.slides.length >= 10) return toast("Instagram allows at most 10 slides", "err");
      ctx.slides.splice(ctx.sel + 1, 0, clone(sl)); ctx.sel++; $("#strip").innerHTML = "";
    } else if (b.hasAttribute("data-rm")) {
      if (!(await confirmDialog("Delete this slide?", `Slide ${ctx.sel + 1} will be removed from the post.`, "Delete", "danger"))) return;
      ctx.slides.splice(ctx.sel, 1); ctx.sel = Math.min(ctx.sel, ctx.slides.length - 1); $("#strip").innerHTML = "";
    } else if (b.id === "regenSlide") {
      return busy(b, async () => {
        try {
          if (ctx.dirty) await save(true);
          adopt(await api(`/api/carousels/${ctx.c.id}/regenerate`, { method: "POST", body: { slide_index: ctx.sel + 1 } }));
          toast(`Slide ${ctx.sel + 1} regenerated`, "ok");
        } catch (err) { toast(err.message, "err"); }
      });
    } else return;
    inspector(); markDirty(); schedulePreview();
  };
}

function splitFact(f) {
  let m = f.match(/^([\d,.]+[kKmM]?)\s+(.*)$/);
  if (m) return [m[1], m[2]];
  if (f.includes(":")) { const [k, ...v] = f.split(":"); return [v.join(":").trim(), k.trim()]; }
  return [f, ""];
}

function addSlide() {
  if (ctx.slides.length >= 10) return toast("Instagram allows at most 10 slides", "err");
  const at = ctx.slides.findIndex((s) => s.layout.startsWith("cta"));
  const idx = at < 0 ? ctx.slides.length : at;
  ctx.slides.splice(idx, 0, { layout: "point", kicker: "Note", title: "New slide", body: "" });
  ctx.sel = idx;
  $("#strip").innerHTML = "";
  markDirty(); inspector(); schedulePreview();
}

// ------------------------------------------------------------------ persistence
function adopt(c) {
  ctx.c = c;
  ctx.slides = clone(c.slide_data.slides);
  ctx.design = clone(c.design);
  ctx.sel = Math.min(ctx.sel, ctx.slides.length - 1);
  ctx.dirty = false;
  const b = $("#aSave");
  if (b) { b.classList.remove("primary"); b.innerHTML = `<i data-lucide="save"></i>Save draft`; icons(b); }
  const sc = $("#statusChip");
  if (sc) mount(sc, badge(c.status));
  $("#strip").innerHTML = "";
  inspector(); renderStatus(); refreshPreview();
}

async function save(silent = false) {
  if (!ctx || ctx.ro) return;
  const { c } = ctx;
  try {
    const out = await api(`/api/carousels/${c.id}`, { method: "PUT", body: { slides: ctx.slides, design: ctx.design, caption: c.caption, hashtags: c.hashtags, cta_keyword: c.cta_keyword, resource_pack: c.resource_pack, headline: c.headline } });
    if (ctx) adopt(out);
    if (!silent) toast(`Saved · QC ${out.quality_score}/100`, "ok");
    return out;
  } catch (e) { toast(e.message, "err"); throw e; }
}

async function renderNow() {
  if (ctx.dirty) await save(true);
  const id = ctx.c.id;
  const el = $("#renderState");
  const j = await ctx.app.startJob(`/api/carousels/${id}/render`, {}, "Render");
  if (!ctx) return;
  if (j && j.status === "SUCCESS") { adopt(await api(`/api/carousels/${id}`)); toast("Slides rendered to 1080×1350 JPG", "ok"); }
  else toast(`Render failed: ${(j && j.error) || "unknown error"}`, "err");
  el && renderStatus();
}

async function rebuild(n) {
  try {
    if (ctx.dirty) await save(true);
    const c = await api(`/api/carousels/${ctx.c.id}/regenerate`, { method: "POST", body: { slides: n } });
    adopt(c);
    toast(c.note || `Rebuilt as ${c.slide_count} slide${c.slide_count > 1 ? "s" : ""}`, c.note ? "info" : "ok");
    layout(); refreshPreview();
  } catch (e) { toast(e.message, "err"); }
}

async function submit() {
  try {
    if (ctx.dirty) await save(true);
    if (ctx.c.render_stale) await renderNow();
    if (!ctx || ctx.c.render_stale) return;
    const c = await api(`/api/carousels/${ctx.c.id}/submit`, { method: "POST" });
    adopt(c);
    toast("Submitted to the Approval Center", "ok");
    ctx.app.refresh();
    ctx.app.go("approval", { id: c.id });
  } catch (e) { toast(e.message, "err"); }
}

async function previewAll() {
  const imgs = !ctx.dirty && !ctx.c.render_stale;
  await modal({
    title: `All ${ctx.slides.length} slides`, wide: true,
    body: html`<p class="dim" style="margin-top:0">${imgs ? "Rendered JPGs — exactly what will be published." : "Live HTML preview (render to produce the final JPGs)."}</p>
      <div class="all-grid">${ctx.slides.map((_, i) => html`<div><div class="frame-box">${imgs ? html`<img src="${ctx.c.rendered[i]}?v=${encodeURIComponent(ctx.c.rendered_at)}" alt="Slide ${i + 1}">` : html`<iframe data-pi="${i}" title="Slide ${i + 1}" sandbox="allow-same-origin" style="transform-origin:0 0"></iframe>`}</div><div class="dim mono" style="font-size:11px;margin-top:6px">${String(i + 1).padStart(2, "0")} · ${LAYOUTS[ctx.slides[i].layout]}</div></div>`)}</div>`,
    onMount: (root) => {
      $$("iframe[data-pi]", root).forEach((f) => {
        paintFrame(f, +f.dataset.pi);
        const w = f.parentElement.clientWidth;
        f.style.transform = `scale(${w / W})`;
      });
    },
  });
}

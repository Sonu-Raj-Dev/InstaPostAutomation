import { $, api, badge, emptyState, esc, html, icon, mount, num, rel, timeIST, toast, busy, ist } from "../ui.js";
import { createScene, webglAvailable } from "../scene.js";

// Workflow nodes in pipeline order. `stage` matches job stage names written by the backend.
export const NODES = [
  { key: "intel", name: "AI Intelligence", short: "INTELLIGENCE", icon: "newspaper", route: ["intelligence", { cat: "AI Industry News" }], stage: /^AI Intelligence/, desc: "AI stories from Hacker News in the last 72 h, with real points and timestamps." },
  { key: "github", name: "GitHub Discovery", short: "GITHUB", icon: "github", route: ["intelligence", { cat: "Trending GitHub" }], stage: /^GitHub Discovery/, desc: "New repositories gaining stars fast, from the GitHub Search API." },
  { key: "tools", name: "Tools Discovery", short: "TOOLS", icon: "boxes", route: ["intelligence", { cat: "Open-Source Projects" }], stage: /^Tools Discovery/, desc: "Trending open models on Hugging Face plus creator & dev tools." },
  { key: "verify", name: "Research Verification", short: "VERIFY", icon: "badge-check", route: ["intelligence", {}], stage: /^(Research Verification|Scoring)/, desc: "Every source is fetched; only reachable originals count as verified." },
  { key: "gen", name: "Content Generation", short: "GENERATE", icon: "sparkles", route: ["creator", {}], stage: /^Content (Selection|Generation)/, desc: "Best verified story becomes a draft with the right format — not always 10 slides." },
  { key: "visual", name: "Visual Creation", short: "VISUALS", icon: "image", route: ["creator", {}], stage: /^Visual Creation/, desc: "HTML design engine rendered to 1080×1350 JPGs by headless Edge." },
  { key: "qa", name: "Quality Assurance", short: "QA", icon: "shield-check", route: ["approval", {}], stage: /^Quality Assurance/, desc: "10 checks on the real slides, caption, CTA and source." },
  { key: "publish", name: "Instagram Publishing", short: "PUBLISH", icon: "send", route: ["approval", {}], stage: /^Instagram Publishing/, desc: "Meta Graph API container flow. Published only when Meta confirms." },
  { key: "engage", name: "Engagement & DM", short: "ENGAGE", icon: "message-circle-heart", route: ["dm", {}], stage: /^Engagement/, desc: "Comment keyword → private reply → resource pack, inside Meta's rules." },
];

function nodeStatus(s) {
  const c = s.counts, src = c.by_source || {};
  const minQ = +s.settings.min_qc_score || 85;
  return [
    src.hn ? ["ok", `${src.hn} stories tracked`] : ["idle", "No stories yet"],
    src.github ? ["ok", `${src.github} repositories tracked`] : ["idle", "No repositories yet"],
    src.hf ? ["ok", `${src.hf} open models tracked`] : ["idle", "No models yet"],
    c.verified_total ? (c.unverified_total > c.verified_total ? ["warn", `${c.verified_total} verified · ${c.unverified_total} unverified`] : ["ok", `${c.verified_total} verified sources`]) : ["idle", "Nothing verified yet"],
    c.drafts + c.pending ? ["ok", `${c.drafts} drafts · ${c.pending} in review`] : ["idle", "No drafts"],
    c.rendered ? ["ok", `${c.rendered} posts rendered`] : ["idle", "Nothing rendered"],
    s.health.avg_qc == null ? ["idle", "No scored drafts"] : s.health.avg_qc >= minQ ? ["ok", `Avg QC ${s.health.avg_qc}/100`] : ["warn", `Avg QC ${s.health.avg_qc} < ${minQ}`],
    !s.meta.token_valid ? ["err", "Meta token invalid — reconnect"] : c.failed ? ["warn", `${c.failed} failed publish`] : ["ok", `${c.published} published`],
    c.campaigns_active ? ["ok", `${c.campaigns_active} active campaign(s)`] : ["idle", "No active campaigns"],
  ];
}

function activeIndex(s) {
  const j = s.running[0];
  if (!j) return -1;
  return NODES.findIndex((n) => n.stage.test(j.stage || ""));
}

let scene = null, off = null;

export default {
  title: "Command Center",
  eyebrow: "SONU AI LAB · Live",
  async render(view, app) {
    app.setActions(html`
      <button class="btn" id="runResearch">${icon("radar")}Run research</button>
      <a class="btn primary" href="#create">${icon("sparkles")}Create a post</a>`);
    mount(view, html`
      <section class="hero" id="hero" tabindex="0" aria-label="Interactive map of the automation pipeline. Use arrow keys to explore stages, Enter to open.">
        <div class="hero-copy">
          <div class="eyebrow"><i></i><span>From AI discovery to creation. Automatically.</span></div>
          <h1>Your AI newsroom.<br><em>Running every day.</em></h1>
          <p>Discover the latest AI developments, create content worth sharing, and publish automatically.</p>
          <ol class="howto"><li><b>1</b>Pick a verified AI tool or a pack</li><li><b>2</b>Check the 3D post and the DM guide</li><li><b>3</b>Publish: commenters get the guide automatically</li></ol>
          <div class="row"><a class="btn primary" href="#create">${icon("sparkles")}Create a post</a><a class="btn" href="#posts">${icon("layout-list")}My posts</a></div>
          <div class="hero-status" id="heroStatus"></div>
        </div>
        <div class="hero-legend" id="legend">Hover a stage · click to open</div>
        <div class="scene-tip" id="tip" style="opacity:0"></div>
      </section>
      <div class="kpis" id="kpis"></div>
      <div class="cc-grid">
        <div class="card"><div class="card-h"><h3>${icon("calendar-clock")}Schedule & pipeline</h3><a class="btn sm ghost" href="#automation">Configure</a></div><div class="card-b" id="sched"></div></div>
        <div class="card"><div class="card-h"><h3>${icon("image")}Latest creative</h3><a class="btn sm ghost" href="#creator">Open studio</a></div><div class="card-b" id="latest"></div></div>
        <div class="card"><div class="card-h"><h3>${icon("activity")}Recent activity</h3></div><div class="card-b"><div class="feed" id="feed"></div></div></div>
      </div>`);

    const hero = $("#hero");
    const tip = $("#tip");
    let statuses = nodeStatus(app.state);
    const nodes = NODES.map((n, i) => ({
      ...n,
      tipHTML: () => {
        const [st, detail] = statuses[i];
        const cls = { ok: "ok", warn: "warn", err: "err", idle: "" }[st];
        const run = activeIndex(app.state) === i;
        return `<b>${esc(n.name)}</b><div class="row" style="margin-top:6px"><span class="chip ${run ? "live" : cls}"><span class="dot"></span>${run ? "Running now" : esc(detail)}</span></div><p>${esc(n.desc)}</p>`;
      },
    }));
    if (webglAvailable()) {
      try {
        scene = createScene(hero, { nodes, tip, onSelect: (n) => app.go(...n.route) });
      } catch (e) { console.warn("WebGL scene failed", e); scene = null; }
    }
    if (!scene) {
      $("#legend").textContent = "3D view unavailable — pipeline list";
      const fb = document.createElement("div");
      fb.className = "scene-fallback";
      mount(fb, html`<ol>${NODES.map((n) => html`<li><a href="#${n.route[0]}">${icon(n.icon)}${n.name}</a></li>`)}</ol>`);
      hero.append(fb);
    }

    const paint = (s) => {
      statuses = nodeStatus(s);
      scene && scene.update(statuses.map((x) => x[0]), activeIndex(s));
      const c = s.counts, m = s.meta;
      mount($("#heroStatus"), html`
        <span class="chip ${s.mode === "AUTO" ? "live" : "info"}">${icon("shield")}${s.mode === "AUTO" ? "Auto Mode" : "Review Mode"}</span>
        ${m.token_valid ? html`<span class="chip ok">${icon("instagram")}@${m.username}</span>` : html`<a class="chip err" href="#settings">${icon("plug-zap")}Instagram disconnected</a>`}
        ${s.running.length ? html`<span class="chip live"><span class="dot"></span>${s.running[0].kind}: ${s.running[0].stage || "starting"}</span>` : ""}`);
      const rate = s.health.rate;
      const kpi = (label, v, d, href, cls = "") => html`<a class="card kpi" href="${href}"><div class="label">${label}</div><div class="v ${cls}">${v}</div><div class="d">${d}</div></a>`;
      mount($("#kpis"), html`
        ${kpi("Discoveries today", num(c.discovered_today), `${num(c.topics_total)} total in library`, "#intelligence")}
        ${kpi("Verified stories", num(c.verified_total), c.verified_today ? `${c.verified_today} verified today` : "Source fetched & reachable", "#intelligence")}
        ${kpi("Content generated", num(c.drafts + c.pending + c.published), `${c.generated_today} today · ${c.drafts} drafts`, "#creator")}
        ${kpi("Approval queue", num(c.pending), c.pending ? "Waiting for you" : "Nothing waiting", "#approval")}
        ${kpi("Published", num(c.published), c.failed ? `${c.failed} failed attempt(s)` : "Confirmed by Meta", "#approval")}
        ${kpi("Automation health", rate == null ? "—" : rate + "%", rate == null ? "No jobs in 7 days" : `${s.health.success_7d}/${s.health.jobs_7d} jobs succeeded (7d)`, "#automation")}`);

      const sc = s.schedule, job = s.running[0];
      mount($("#sched"), html`<div class="sched">
        ${job ? html`<div class="job"><div class="spread"><span class="chip live"><span class="dot"></span>${job.kind} #${job.id}</span><span class="mono dim">${job.progress}%</span></div><div>${job.stage || "Starting…"}</div><div class="progress"><i style="width:${job.progress}%"></i></div></div>` : ""}
        <div class="sched-item"><div class="t">${sc.research_time}</div><div class="k"><b>Daily research</b><div class="dim">${sc.enabled ? "Next " + rel(sc.research) : "Scheduler paused"}</div></div></div>
        <div class="sched-item"><div class="t">${sc.publish_time}</div><div class="k"><b>${s.mode === "AUTO" ? "Auto publish" : "Build & queue for review"}</b><div class="dim">${sc.enabled ? "Next " + rel(sc.pipeline) : "Scheduler paused"} · IST</div></div></div>
        <div class="row dim" style="font-size:12.5px">${icon("history")}Last successful research: ${sc.last_research_ok ? ist(sc.last_research_ok) : "never"}</div>
      </div>`);

      const L = s.latest;
      mount($("#latest"), L ? html`<div style="display:grid;grid-template-columns:120px 1fr;gap:16px;align-items:start">
          <a href="#creator?id=${L.id}" style="display:block;border-radius:10px;overflow:hidden;border:1px solid var(--line-2);aspect-ratio:4/5;background:#000">
            ${L.rendered.length ? html`<img src="${L.rendered[0]}?v=${encodeURIComponent(L.rendered_at)}" alt="Cover slide" style="width:100%;height:100%;object-fit:cover">` : html`<iframe title="Cover preview" src="/api/carousels/${L.id}/slides/1.html" style="width:1080px;height:1350px;border:0;transform:scale(${120 / 1080});transform-origin:0 0;pointer-events:none"></iframe>`}</a>
          <div class="stack"><b style="font:600 16px/1.25 var(--f-display);overflow-wrap:anywhere">${L.headline}</b>
            <div class="row">${badge(L.status)}<span class="chip">${L.slide_count} slide${L.slide_count > 1 ? "s" : ""}</span><span class="chip ${L.quality_score >= (+s.settings.min_qc_score || 85) ? "ok" : "warn"}">QC ${L.quality_score}</span></div>
            <div class="dim" style="font-size:12.5px">${L.topic.category || ""} · updated ${rel(L.updated_at)}</div>
            <div class="row"><a class="btn sm" href="#creator?id=${L.id}">${icon("pen-tool")}Edit</a>${L.status === "PENDING_APPROVAL" ? html`<a class="btn sm" href="#approval?id=${L.id}">${icon("shield-check")}Review</a>` : ""}</div></div></div>`
        : emptyState("image", "No creatives yet", "Pick a verified story in Daily Intelligence and turn it into a post.", html`<a class="btn sm primary" href="#intelligence">Browse stories</a>`));

      const ico = { research: "radar", creative: "image", approval: "shield-check", publish: "send", settings: "settings-2", dm: "message-circle", pipeline: "workflow", render: "image", dm_scan: "message-circle" };
      mount($("#feed"), s.activity.length ? html`${s.activity.map((e) => html`<div class="feed-item">${icon(ico[e.kind] || "dot")}<div>${e.message}</div><time title="${ist(e.ts)}">${rel(e.ts)}</time></div>`)}`
        : emptyState("activity", "No activity yet", "Research runs, drafts, approvals and publishes will appear here."));
    };
    paint(app.state);
    off = app.on(paint);

    $("#runResearch").onclick = (e) => busy(e.currentTarget, async () => {
      try {
        const j = await app.startJob("/api/research/run", {}, "Research");
        if (j) toast(j.status === "SUCCESS" ? `Research finished: ${JSON.parse(j.result_json || "{}").found ?? 0} new stories` : `Research failed: ${j.error}`, j.status === "SUCCESS" ? "ok" : "err");
      } catch (err) { toast(err.message, "err"); }
    });
  },
  destroy() {
    off && off();
    scene && scene.destroy();
    scene = null;
  },
};

import { $, $$, api, badge, busy, confirmDialog, emptyState, html, icon, ist, mount, rel, toast } from "../ui.js";

// Each stage names the real backend function it runs. Status is derived from real state only.
const STAGES = [
  { name: "Daily Scheduler", fn: "scheduler.tick()", icon: "alarm-clock", re: null },
  { name: "Research Engine", fn: "harvester.run_daily_harvest()", icon: "radar", re: /^(AI Intelligence|GitHub Discovery|Tools Discovery)/ },
  { name: "Source Verification", fn: "harvester.verify()", icon: "badge-check", re: /^(Research Verification|Scoring)/ },
  { name: "Content Selection", fn: "workflow.run_pipeline()", icon: "filter", re: /^Content Selection/ },
  { name: "Creative Generation", fn: "creative.build_slides() + render", icon: "sparkles", re: /^(Content Generation|Visual Creation)/ },
  { name: "Quality Assurance", fn: "QualityControlEvaluator.evaluate()", icon: "shield-check", re: /^Quality Assurance/ },
  { name: "Approval / Auto", fn: "workflow.submit()", icon: "user-check", re: null },
  { name: "Instagram Publishing", fn: "workflow.publish()", icon: "send", re: /^Instagram Publishing/ },
  { name: "Performance Analysis", fn: "/api/analytics", icon: "line-chart", re: null },
];

let off = null;

export default {
  title: "Automation Studio",
  eyebrow: "Automate · Asia/Kolkata",
  async render(view, app) {
    let jobs = [], filter = "";
    app.setActions(html`<button class="btn" id="runR">${icon("radar")}Run research</button><button class="btn primary" id="runP">${icon("play")}Run full pipeline</button>`);
    mount(view, html`
      <div class="card"><div class="card-h"><h3>${icon("workflow")}Pipeline</h3><span class="dim" style="font-size:12px">Live status from the jobs table · nothing here is simulated</span></div><div class="card-b"><div class="pipeline" id="pipe"></div></div></div>
      <div class="auto-grid">
        <div class="card"><div class="card-h"><h3>${icon("sliders-horizontal")}Configuration</h3></div><div class="card-b"><form class="stack" id="cfg" style="gap:16px" novalidate></form></div></div>
        <div class="card"><div class="card-h"><h3>${icon("list")}Jobs</h3><div class="seg" id="jf">${[["", "All"], ["research", "Research"], ["pipeline", "Pipeline"], ["render", "Render"], ["publish", "Publish"], ["dm_scan", "DM"]].map(([k, l]) => html`<button data-k="${k}" class="${k === filter ? "on" : ""}">${l}</button>`)}</div></div>
          <div class="card-b"><div class="row" id="jobStats" style="margin-bottom:12px"></div><div class="table-wrap"><table class="table"><thead><tr><th>Job</th><th>Status</th><th>Stage / result</th><th>Started</th><th>Duration</th><th></th></tr></thead><tbody id="jobsBody"></tbody></table></div></div></div>
      </div>`);

    const drawPipe = () => {
      const s = app.state, c = s.counts, j = s.running[0];
      const last = (k) => jobs.find((x) => x.kind === k);
      const lastR = last("research"), lastP = last("pipeline"), lastPub = last("publish");
      const st = (status, sub) => ({ status, sub });
      const info = [
        s.schedule.enabled ? st("ok", `Research ${s.schedule.research_time} · Build ${s.schedule.publish_time}`) : st("off", "Paused"),
        lastR ? st(lastR.status === "FAILED" ? "err" : "ok", `Last run ${rel(lastR.started_at)}`) : st("idle", "Never run"),
        c.verified_total ? st("ok", `${c.verified_total} verified · ${c.unverified_total} not`) : st("idle", "Nothing verified"),
        lastP ? st(lastP.status === "FAILED" ? "warn" : "ok", lastP.status === "FAILED" ? (lastP.error || "").slice(0, 60) : `Last ${rel(lastP.started_at)}`) : st("idle", "Pipeline never run"),
        c.rendered ? st("ok", `${c.rendered} rendered`) : st("idle", "No renders"),
        s.health.avg_qc == null ? st("idle", "No scores") : st(s.health.avg_qc >= +s.settings.min_qc_score ? "ok" : "warn", `Avg ${s.health.avg_qc} · min ${s.settings.min_qc_score}`),
        st(s.mode === "AUTO" ? "warn" : "ok", s.mode === "AUTO" ? "Auto Mode — publishes if QC passes" : `Review Mode · ${c.pending} waiting`),
        !s.meta.token_valid ? st("err", "Meta token invalid") : lastPub ? st(lastPub.status === "FAILED" ? "err" : "ok", `Last ${rel(lastPub.started_at)}`) : st("ok", `${c.published} published`),
        s.meta.token_valid ? st("ok", "Live from Graph API") : st("off", "Needs Instagram connection"),
      ];
      mount($("#pipe"), html`${STAGES.map((g, i) => {
        const run = j && g.re && g.re.test(j.stage || "");
        const x = info[i];
        return html`<div class="pipe-node ${run ? "run" : x.status}"><div class="orb">${icon(g.icon)}</div><b>${g.name}</b><small>${run ? j.stage : x.sub}</small><code>${g.fn}</code></div>`;
      })}`);
    };

    const drawCfg = () => {
      const s = app.state.settings, cats = (s.auto_categories || "").split(",");
      mount($("#cfg"), html`
        <div class="field"><span>Publishing mode</span><div class="mode-cards" id="modes">
          <label class="${s.publishing_mode !== "AUTO" ? "on" : ""}"><input type="radio" name="publishing_mode" value="REVIEW" ${s.publishing_mode !== "AUTO" ? "checked" : ""}><b>${icon("shield-check")}Review Mode</b>Builds the post and waits for your approval. Default.</label>
          <label class="${s.publishing_mode === "AUTO" ? "on" : ""}"><input type="radio" name="publishing_mode" value="AUTO" ${s.publishing_mode === "AUTO" ? "checked" : ""}><b>${icon("zap")}Auto Mode</b>Publishes unattended when QC passes. Needs confirmation.</label></div></div>
        <div class="grid" style="grid-template-columns:1fr 1fr">
          <label class="field" data-f="research_time"><span>Research time</span><input class="input" type="time" name="research_time" value="${s.research_time}" required></label>
          <label class="field" data-f="target_publish_time"><span>Publishing time</span><input class="input" type="time" name="target_publish_time" value="${s.target_publish_time}" required></label></div>
        <label class="field"><span>Timezone</span><input class="input" value="Asia/Kolkata (IST, UTC+05:30)" disabled><small>Fixed to IST for this account.</small></label>
        <div class="grid" style="grid-template-columns:1fr 1fr">
          <label class="field" data-f="min_qc_score"><span>Minimum content score</span><input class="input" type="number" min="0" max="100" name="min_qc_score" value="${s.min_qc_score}"></label>
          <label class="field" data-f="max_posts_per_day"><span>Max posts per day</span><input class="input" type="number" min="1" max="5" name="max_posts_per_day" value="${s.max_posts_per_day}"></label></div>
        <div class="field" data-f="auto_categories"><span>Research categories</span><div class="cat-checks">${app.state.categories.map((c) => html`<label><input type="checkbox" name="cat" value="${c}" ${cats.includes(c) ? "checked" : ""}>${c}</label>`)}</div></div>
        <label class="row" style="justify-content:space-between"><span><b style="font-weight:600">Scheduler</b><br><span class="dim" style="font-size:12px">Run research and build daily at the times above</span></span><span class="switch"><input type="checkbox" name="scheduler_enabled" ${s.scheduler_enabled === "1" ? "checked" : ""}><i></i></span></label>
        <div class="row"><button class="btn primary" type="submit">${icon("save")}Save configuration</button><span class="dim" style="font-size:12px" id="nextRuns">Next research ${rel(app.state.schedule.research)} · next build ${rel(app.state.schedule.pipeline)}</span></div>`);
      $("#modes").onclick = (e) => { const l = e.target.closest("label"); if (l) $$("#modes label").forEach((x) => x.classList.toggle("on", x === l)); };
    };

    const drawJobs = () => {
      const rows = jobs.filter((j) => !filter || j.kind === filter);
      const done = jobs.filter((j) => j.status !== "RUNNING");
      mount($("#jobStats"), html`<span class="chip live"><span class="dot"></span>${jobs.filter((j) => j.status === "RUNNING").length} active</span><span class="chip ok">${done.filter((j) => j.status === "SUCCESS").length} completed</span><span class="chip err">${done.filter((j) => j.status === "FAILED").length} failed</span>
        <span class="dim" style="font-size:12px">Last execution ${jobs[0] ? rel(jobs[0].started_at) : "never"}</span>`);
      const dur = (j) => { if (!j.finished_at) return "—"; const s = Math.round((new Date(j.finished_at.replace(" ", "T")) - new Date(j.started_at.replace(" ", "T"))) / 1000); return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`; };
      const summary = (j) => {
        if (j.status === "RUNNING") return html`${j.stage}<div class="progress" style="margin-top:6px"><i style="width:${j.progress}%"></i></div>`;
        if (j.status === "FAILED") return html`<span style="color:var(--err)">${(j.error || "").slice(0, 120)}</span>`;
        try { const r = JSON.parse(j.result_json || "{}"); return Object.entries(r).filter(([k, v]) => typeof v !== "object").slice(0, 3).map(([k, v]) => `${k}: ${v}`).join(" · "); } catch { return ""; }
      };
      mount($("#jobsBody"), rows.length ? html`${rows.map((j) => html`<tr><td><b>${j.kind}</b> <span class="dim mono">#${j.id}</span><div class="dim" style="font-size:11.5px">${j.trigger}</div></td><td>${badge(j.status)}</td><td style="max-width:340px;font-size:12.5px">${summary(j)}</td><td title="${ist(j.started_at)}" style="white-space:nowrap">${rel(j.started_at)}</td><td class="mono">${dur(j)}</td><td><button class="btn sm ghost" data-log="${j.id}">${icon("scroll-text")}Log</button></td></tr>`)}`
        : html`<tr><td colspan="6">${emptyState("list", "No jobs yet", "Run research or the full pipeline to see executions here.")}</td></tr>`);
    };

    const load = async () => { jobs = await api("/api/jobs?limit=80"); drawJobs(); drawPipe(); };
    drawCfg();
    await load();
    let was = app.state.running.length;
    off = app.on((s) => { drawPipe(); if (was || s.running.length) load(); was = s.running.length; $("#nextRuns") && ($("#nextRuns").textContent = `Next research ${rel(s.schedule.research)} · next build ${rel(s.schedule.pipeline)}`); });

    $("#jf").onclick = (e) => { const b = e.target.closest("[data-k]"); if (b) { filter = b.dataset.k; $$("#jf button").forEach((x) => x.classList.toggle("on", x === b)); drawJobs(); } };
    $("#jobsBody").onclick = (e) => { const b = e.target.closest("[data-log]"); if (b) showLog(+b.dataset.log); };
    $("#cfg").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target, body = {
        publishing_mode: f.publishing_mode.value, research_time: f.research_time.value, target_publish_time: f.target_publish_time.value,
        min_qc_score: f.min_qc_score.value, max_posts_per_day: f.max_posts_per_day.value,
        auto_categories: $$("input[name=cat]:checked", f).map((x) => x.value).join(","), scheduler_enabled: f.scheduler_enabled.checked ? "1" : "0",
      };
      $$(".field", f).forEach((x) => { x.classList.remove("bad"); const er = x.querySelector(".err"); er && er.remove(); });
      if (!body.auto_categories) return markBad(f, { auto_categories: "Pick at least one category" });
      if (body.publishing_mode === "AUTO" && app.state.settings.publishing_mode !== "AUTO") {
        const ok = await confirmDialog("Enable Auto Mode?", `At ${body.target_publish_time} IST the pipeline will publish to @${app.state.meta.username || "your account"} without asking, whenever QC ≥ ${body.min_qc_score}. Keep Review Mode until you've tested the full flow.`, "Enable Auto Mode", "danger");
        if (!ok) return;
        body.confirm_auto = true;
      }
      const btn = f.querySelector("[type=submit]");
      busy(btn, async () => {
        try { await api("/api/settings", { method: "POST", body }); toast("Configuration saved", "ok"); await app.refresh(); drawCfg(); }
        catch (err) { err.fields ? markBad(f, err.fields) : toast(err.message, "err"); }
      });
    };
    const run = (path, label) => (e) => busy(e.currentTarget, async () => {
      try {
        const j = await app.startJob(path, {}, label);
        await load();
        if (j) toast(j.status === "SUCCESS" ? `${label} finished` : `${label} failed: ${j.error}`, j.status === "SUCCESS" ? "ok" : "err", 7000);
      } catch (err) { toast(err.message, "err"); }
    });
    $("#runR").onclick = run("/api/research/run", "Research");
    $("#runP").onclick = async (e) => {
      const s = app.state;
      if (!(await confirmDialog("Run the full pipeline now?", s.mode === "AUTO" ? "Auto Mode is ON: if QC passes, this publishes to Instagram." : "Review Mode: research → pick best verified story → create, render and score a post → queue it for your approval. Nothing is published.", "Run pipeline"))) return;
      run("/api/automation/run-now", "Pipeline")(e);
    };
  },
  destroy() { off && off(); },
};

function markBad(form, fields) {
  Object.entries(fields).forEach(([k, msg]) => {
    const f = form.querySelector(`[data-f="${k}"]`);
    if (!f) return toast(`${k}: ${msg}`, "err");
    f.classList.add("bad");
    f.insertAdjacentHTML("beforeend", `<span class="err">${msg}</span>`);
  });
}

async function showLog(id) {
  const j = await api(`/api/jobs/${id}`);
  const d = document.createElement("div");
  d.className = "log-drawer";
  d.setAttribute("role", "dialog");
  mount(d, html`<div class="card-h" style="padding:18px 20px"><h3>${icon("scroll-text")}${j.kind} #${j.id}</h3><button class="btn sm icon ghost" data-x aria-label="Close">${icon("x")}</button></div>
    <div style="padding:0 20px 20px;overflow:auto;display:grid;gap:12px;align-content:start">
      <div class="row">${badge(j.status)}<span class="chip">${j.trigger}</span><span class="dim" style="font-size:12px">${ist(j.started_at)} → ${j.finished_at ? ist(j.finished_at) : "running"}</span></div>
      ${j.error ? html`<div class="notice err">${icon("alert-triangle")}<div><b>Failure reason</b><br>${j.error}</div></div>` : ""}
      <div class="label">Log</div><pre class="pre" style="max-height:none">${j.log || "(no log lines)"}</pre>
      ${j.result_json ? html`<div class="label">Result</div><pre class="pre">${JSON.stringify(JSON.parse(j.result_json), null, 2)}</pre>` : ""}</div>`);
  const close = () => { d.remove(); document.removeEventListener("keydown", k); };
  const k = (e) => e.key === "Escape" && close();
  d.onclick = (e) => e.target.closest("[data-x]") && close();
  document.addEventListener("keydown", k);
  document.body.append(d);
}

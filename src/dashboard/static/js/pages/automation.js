import { $, $$, api, badge, busy, confirmDialog, emptyState, html, icon, ist, modal, mount, rel, toast } from "../ui.js";

// Phase 6: one card per independent system. Every value comes from /api/automation/overview (jobs, webhook_events,
// dm_deliveries, settings). Nothing is hardcoded or simulated.
const SYSTEMS = [
  { key: "research", name: "Research", icon: "radar", run: "research", next: "daily" },
  { key: "generate", name: "Content generation", icon: "sparkles", run: "generate", next: "daily" },
  { key: "publishing", name: "Publishing", icon: "send", run: "publish_due", next: "daily" },
  { key: "comments", name: "Comment monitoring", icon: "message-square", run: null, next: "event" },
  { key: "dm", name: "DM delivery", icon: "message-circle-heart", run: null, next: "event" },
  { key: "analytics", name: "Analytics", icon: "line-chart", run: "analytics", next: "daily" },
];
const SYS_ST = { OK: ["Healthy", "ok"], FAILED: ["Needs attention", "err"], RUNNING: ["Running", "live"], NEVER: ["No runs yet", ""] };
const yesNo = (v, yes = "Yes", no = "No") => v ? html`<span class="chip ok">${yes}</span>` : html`<span class="chip err">${no}</span>`;

let off = null;

export default {
  title: "Automation Studio",
  eyebrow: "Automate · Asia/Kolkata",
  async render(view, app) {
    let jobs = [], filter = "";
    let ov = null;
    app.setActions(html`<button class="btn" id="runR">${icon("radar")}Run research</button><button class="btn primary" id="runP">${icon("play")}Run full pipeline</button>`);
    mount(view, html`
      <div class="card"><div class="card-h"><h3>${icon("workflow")}Systems</h3><span class="dim" style="font-size:12px">Each runs on its own · live from the database · nothing simulated</span></div><div class="card-b"><div class="grid" id="systems" style="grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px"></div></div></div>
      <div class="card" style="margin-top:16px"><div class="card-h"><h3>${icon("activity")}Webhook health</h3><span class="dim" style="font-size:12px">Real-time comment events from Meta → QStash → DM engine</span></div><div class="card-b" id="whealth"></div></div>
      <div class="auto-grid">
        <div class="card"><div class="card-h"><h3>${icon("sliders-horizontal")}Configuration</h3></div><div class="card-b"><form class="stack" id="cfg" style="gap:16px" novalidate></form></div></div>
        <div class="card"><div class="card-h"><h3>${icon("list")}Jobs</h3><div class="seg" id="jf">${[["", "All"], ["research", "Research"], ["generate", "Generate"], ["publish_due", "Publish due"], ["publish", "Publish"], ["analytics", "Analytics"], ["maintenance", "Maintenance"], ["dm_scan", "DM"]].map(([k, l]) => html`<button data-k="${k}" class="${k === filter ? "on" : ""}">${l}</button>`)}</div></div>
          <div class="card-b"><div class="row" id="jobStats" style="margin-bottom:12px"></div><div class="table-wrap"><table class="table"><thead><tr><th>Job</th><th>Status</th><th>Stage / result</th><th>Started</th><th>Duration</th><th></th></tr></thead><tbody id="jobsBody"></tbody></table></div></div></div>
      </div>`);

    const drawSystems = () => {
      if (!ov) return;
      mount($("#systems"), html`${SYSTEMS.map((g) => {
        const x = ov.systems[g.key] || {}, [lbl, cls] = SYS_ST[x.status] || SYS_ST.NEVER;
        const last = x.last ? html`${rel(x.last.started_at)} ${badge(x.last.status)}` : x.last_received_at ? rel(x.last_received_at) : x.last_sent_at ? rel(x.last_sent_at) : "—";
        const next = g.next === "event" ? "On each comment (webhook)" : !ov.enabled ? "Scheduler paused" : x.next_at ? html`${rel(x.next_at)} <span class="dim">(${ist(x.next_at, { timeStyle: "short" })})</span>` : "—";
        const e = x.latest_error;
        return html`<div class="card" style="box-shadow:none"><div class="card-b stack" style="gap:10px">
          <div class="spread"><b class="row" style="gap:8px">${icon(g.icon)}${g.name}</b><span class="chip ${cls}">${x.status === "RUNNING" ? html`<span class="dot"></span>` : ""}${lbl}</span></div>
          ${x.running ? html`<div class="job"><div>${x.running.stage || "Starting…"}</div><div class="progress"><i style="width:${x.running.progress || 5}%"></i></div></div>` : ""}
          <dl class="kv" style="font-size:12.5px"><dt>${g.key === "comments" ? "Last event" : g.key === "dm" ? "Last DM sent" : "Last run"}</dt><dd>${last}</dd><dt>Next</dt><dd>${next}</dd>
            <dt>7 days</dt><dd><span class="chip ok">${x.success_7d || 0} ok</span> <span class="chip ${x.failed_7d ? "err" : ""}">${x.failed_7d || 0} failed</span>${x.pending ? html` <span class="chip warn">${x.pending} waiting</span>` : ""}</dd>
            ${g.key === "publishing" && x.posts ? html`<dt>Posts</dt><dd>${x.posts.scheduled} scheduled${x.posts.next_scheduled ? html` (next ${ist(x.posts.next_scheduled.scheduled_for, { dateStyle: "short", timeStyle: "short" })})` : ""} · ${x.posts.failed} failed${x.posts.in_progress ? ` · ${x.posts.in_progress} in progress` : ""}</dd>` : ""}
            ${g.key === "dm" && x.counts ? html`<dt>Totals</dt><dd>${x.counts.RESOURCE_SENT || 0} guides sent · ${(x.counts.AWAITING_TAP || 0) + (x.counts.AWAITING_FOLLOW || 0)} waiting</dd>` : ""}</dl>
          ${e && (e.error || "").trim() ? html`<div class="notice err" style="font-size:12px">${icon("alert-triangle")}<div><b>Latest error</b> <span class="dim">${rel(e.finished_at || e.updated_at || e.received_at)}</span><br><span style="overflow-wrap:anywhere">${e.error.slice(0, 220)}</span></div></div>` : ""}
          <div class="row" style="gap:6px">
            ${g.run ? html`<button class="btn sm" data-run="${g.run}" data-name="${g.name}">${icon("play")}Run now</button>` : ""}
            ${x.last ? html`<button class="btn sm ghost" data-log="${x.last.id}">${icon("scroll-text")}Log</button>` : ""}
            ${g.key === "comments" ? html`<button class="btn sm" data-sweep>${icon("refresh-ccw")}Process waiting</button>` : ""}
            ${g.key === "dm" || g.key === "comments" ? html`<a class="btn sm ghost" href="#dm">${icon("external-link")}Details</a>` : ""}
            ${g.key === "publishing" && x.posts && x.posts.failed ? html`<a class="btn sm ghost" href="#approval">${icon("external-link")}Failed posts</a>` : ""}</div>
        </div></div>`;
      })}`);
      const w = ov.webhook, q = w.qstash, sub = w.subscription || {}, ev = w.events || {};
      mount($("#whealth"), html`<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px">
        <dl class="kv" style="font-size:12.5px">
          <dt>Meta verification</dt><dd>${w.verified_at ? html`<span class="chip ok">Verified</span> <span class="dim">${rel(w.verified_at)}</span>` : html`<span class="chip warn">Not verified yet</span>`}</dd>
          <dt>App secret</dt><dd>${yesNo(w.app_secret_configured, "Configured", "Missing")}${w.app_secret_configured ? "" : html`<div class="dim" style="font-size:11.5px">Webhooks are rejected until META_APP_SECRET is set</div>`}</dd>
          <dt>Subscriptions</dt><dd>${sub.checked_at ? html`comments ${yesNo(sub.comments)} · messages ${yesNo(sub.messages)} · page ${yesNo(sub.page_subscribed)} <span class="dim">checked ${rel(sub.checked_at)}</span>` : html`<span class="chip">Unknown</span><div class="dim" style="font-size:11.5px">${sub.note || ""}</div>`}</dd>
          ${w.callback_url ? html`<dt>Callback URL</dt><dd class="mono" style="overflow-wrap:anywhere">${w.callback_url}</dd>` : ""}
          <dt>Meta setup</dt><dd><button class="btn sm" id="auditM">${icon("search-check")}Check Meta configuration</button><div class="dim" style="font-size:11.5px">Read-only: changes nothing at Meta</div></dd></dl>
        <dl class="kv" style="font-size:12.5px">
          <dt>Last event received</dt><dd>${w.last_received_at ? html`${rel(w.last_received_at)} <span class="dim">${ist(w.last_received_at)}</span>` : "Never"}</dd>
          <dt>Last event processed</dt><dd>${w.last_processed_at ? rel(w.last_processed_at) : "Never"}</dd>
          <dt>Last successful DM</dt><dd>${w.last_dm_at ? rel(w.last_dm_at) : "Never"}</dd>
          <dt>Failed DMs</dt><dd>${w.failed_dm_count ? html`<span class="chip err">${w.failed_dm_count}</span> <a href="#dm">review</a>` : html`<span class="chip ok">0</span>`}</dd></dl>
        <dl class="kv" style="font-size:12.5px">
          <dt>QStash</dt><dd>${yesNo(q.configured, "Configured", "Not configured")}${q.configured ? html` ${yesNo(q.can_verify, "Keys set", "Keys missing")}` : html`<div class="dim" style="font-size:11.5px">Scheduled jobs and queued events need QSTASH_TOKEN</div>`}</dd>
          <dt>Event queue</dt><dd>${["PENDING", "QUEUED", "PROCESSING", "PROCESSED", "IGNORED", "FAILED"].filter((k) => ev[k]).map((k) => html`${badge(k)} ${ev[k]} `)}${Object.keys(ev).length ? "" : "No events yet"}</dd>
          <dt>Schedules</dt><dd>${q.last_sync_at ? html`${q.schedules} synced ${rel(q.last_sync_at)}` : "Never synced"} ${q.sync_error ? html`<div style="color:var(--err);font-size:11.5px">${q.sync_error}</div>` : ""} <button class="btn sm ghost" id="syncQ" ${q.configured ? "" : "disabled"}>${icon("refresh-ccw")}Sync now</button></dd></dl></div>`);
    };
    const loadOverview = async () => { try { ov = await api("/api/automation/overview"); drawSystems(); } catch (e) { /* keep last good view */ } };

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
      void info; void j;
    };

    const drawCfg = () => {
      const s = app.state.settings, cats = (s.auto_categories || "").split(",");
      mount($("#cfg"), html`
        <div class="field"><span>Publishing mode</span><div class="mode-cards" id="modes">
          <label class="${s.publishing_mode !== "AUTO" ? "on" : ""}"><input type="radio" name="publishing_mode" value="REVIEW" ${s.publishing_mode !== "AUTO" ? "checked" : ""}><b>${icon("shield-check")}Review Mode</b>Builds the post and waits for your approval. Default.</label>
          <label class="${s.publishing_mode === "AUTO" ? "on" : ""}"><input type="radio" name="publishing_mode" value="AUTO" ${s.publishing_mode === "AUTO" ? "checked" : ""}><b>${icon("zap")}Auto Mode</b>Approves posts that pass QC and publishes them at the publishing time. Needs confirmation.</label></div></div>
        <div class="grid" style="grid-template-columns:1fr 1fr">
          <label class="field" data-f="research_time"><span>Research time</span><input class="input" type="time" name="research_time" value="${s.research_time}" required></label>
          <label class="field" data-f="target_publish_time"><span>Publishing time</span><input class="input" type="time" name="target_publish_time" value="${s.target_publish_time}" required></label></div>
        <div class="grid" style="grid-template-columns:1fr 1fr">
          <label class="field" data-f="generate_time"><span>Content generation time</span><input class="input" type="time" name="generate_time" value="${s.generate_time || ""}"><small>Empty = 45 min before publishing</small></label>
          <label class="field" data-f="analytics_time"><span>Analytics time</span><input class="input" type="time" name="analytics_time" value="${s.analytics_time || "23:30"}" required></label></div>
        <label class="field"><span>Timezone</span><input class="input" value="Asia/Kolkata (IST, UTC+05:30)" disabled><small>Fixed to IST for this account.</small></label>
        <div class="grid" style="grid-template-columns:1fr 1fr">
          <label class="field" data-f="min_qc_score"><span>Minimum content score</span><input class="input" type="number" min="0" max="100" name="min_qc_score" value="${s.min_qc_score}"></label>
          <label class="field" data-f="max_posts_per_day"><span>Max posts per day</span><input class="input" type="number" min="1" max="5" name="max_posts_per_day" value="${s.max_posts_per_day}"></label></div>
        <div class="field" data-f="auto_categories"><span>Research categories</span><div class="cat-checks">${app.state.categories.map((c) => html`<label><input type="checkbox" name="cat" value="${c}" ${cats.includes(c) ? "checked" : ""}>${c}</label>`)}</div></div>
        <label class="row" style="justify-content:space-between"><span><b style="font-weight:600">Scheduler</b><br><span class="dim" style="font-size:12px">Research, generation, publishing and analytics each run at their own time above</span></span><span class="switch"><input type="checkbox" name="scheduler_enabled" ${s.scheduler_enabled === "1" ? "checked" : ""}><i></i></span></label>
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

    const load = async () => { jobs = await api("/api/jobs?limit=80"); drawJobs(); drawPipe(); loadOverview(); };
    drawCfg();
    await load();
    let was = app.state.running.length;
    off = app.on((s) => { drawPipe(); if (was || s.running.length) load(); was = s.running.length; $("#nextRuns") && ($("#nextRuns").textContent = `Next research ${rel(s.schedule.research)} · next build ${rel(s.schedule.pipeline)}`); });

    $("#jf").onclick = (e) => { const b = e.target.closest("[data-k]"); if (b) { filter = b.dataset.k; $$("#jf button").forEach((x) => x.classList.toggle("on", x === b)); drawJobs(); } };
    $("#jobsBody").onclick = (e) => { const b = e.target.closest("[data-log]"); if (b) showLog(+b.dataset.log); };
    $("#systems").onclick = async (e) => {
      const lg = e.target.closest("[data-log]"), rn = e.target.closest("[data-run]"), sw = e.target.closest("[data-sweep]");
      if (lg) return showLog(+lg.dataset.log);
      if (sw) return busy(sw, async () => { try { const r = await api("/api/inbox/sweep", { method: "POST" }); toast(`${r.found} waiting event(s): ${r.requeued || 0} re-queued, ${r.processed || 0} processed`, "ok"); loadOverview(); } catch (err) { toast(err.message, "err"); } });
      if (rn) {
        const kind = rn.dataset.run, pub = kind === "publish_due";
        if (pub && !(await confirmDialog("Publish due posts now?", "Publishes the oldest approved post whose scheduled time has passed (one per run). Nothing else is published.", "Publish due post", "publish"))) return;
        busy(rn, async () => {
          try {
            const j = await app.startJob(`/api/automation/run/${kind}`, pub ? { confirm: true } : {}, rn.dataset.name);
            if (j) toast(j.status === "SUCCESS" ? `${rn.dataset.name} finished` : `${rn.dataset.name} failed: ${j.error}`, j.status === "SUCCESS" ? "ok" : "err", 8000);
            await load();
          } catch (err) { toast(err.message, "err"); }
        });
      }
    };
    $("#whealth").onclick = (e) => {
      const a = e.target.closest("#auditM");
      if (a) return busy(a, async () => {
        try {
          const r = await api("/api/meta/audit", { method: "POST" });
          await modal({ title: "Meta configuration (read-only check)", body: html`<div class="stack">
            ${r.errors.length ? html`<div class="notice err">${icon("alert-triangle")}<div><b>Problems</b><ul style="margin:6px 0 0;padding-left:18px">${r.errors.map((x) => html`<li>${x}</li>`)}</ul></div></div>` : html`<div class="notice info">${icon("check-circle-2")}<div>No problems found in what the API exposes.</div></div>`}
            ${r.actions.length ? html`<div class="notice warn">${icon("list-checks")}<div><b>To do</b><ul style="margin:6px 0 0;padding-left:18px">${r.actions.map((x) => html`<li>${x}</li>`)}</ul></div></div>` : ""}
            <dl class="kv" style="font-size:12.5px"><dt>Token</dt><dd>${r.token ? html`${r.token.type || "?"} · ${r.token.valid ? "valid" : "INVALID"} · ${r.token.never_expires ? "never expires" : r.token.expires_at ? "expires " + ist(r.token.expires_at) : "expiry unknown"}` : "—"}</dd>
              <dt>Page</dt><dd>${r.page ? `${r.page.name} (${r.page.id})` : "—"}</dd><dt>Instagram</dt><dd>${r.instagram && r.instagram.username ? "@" + r.instagram.username : "—"}</dd>
              <dt>Permissions</dt><dd>${r.permissions ? html`${r.permissions.granted.join(", ") || "none"}${Object.keys(r.permissions.missing).length ? html`<div style="color:var(--err)">missing: ${Object.keys(r.permissions.missing).join(", ")}</div>` : ""}` : "—"}</dd>
              <dt>Webhook fields</dt><dd>comments ${String(r.webhook_fields && r.webhook_fields.comments)} · messages ${String(r.webhook_fields && r.webhook_fields.messages)}</dd>
              <dt>Page subscribed</dt><dd>${String(r.page_subscribed)}</dd><dt>Messaging</dt><dd>${r.messaging ? r.messaging.note : "—"}</dd>
              <dt>App mode</dt><dd class="dim">${r.app ? r.app.mode : "—"}</dd><dt>Advanced Access</dt><dd class="dim">${r.app ? r.app.advanced_access : "—"}</dd></dl></div>` });
          loadOverview();
        } catch (err) { toast(err.message, "err"); }
      });
      const b = e.target.closest("#syncQ");
      if (b) busy(b, async () => { try { const r = await api("/api/scheduler/sync", { method: "POST" }); toast(r.ok ? `QStash schedules synced (${r.upserted.length})` : `Sync failed: ${(r.errors || [r.error]).join("; ")}`, r.ok ? "ok" : "err", 8000); loadOverview(); } catch (err) { toast(err.message, "err"); } });
    };
    $("#cfg").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target, body = {
        publishing_mode: f.publishing_mode.value, research_time: f.research_time.value, target_publish_time: f.target_publish_time.value,
        generate_time: f.generate_time.value, analytics_time: f.analytics_time.value,
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
        try {
          const r = await api("/api/settings", { method: "POST", body });
          const sy = r.schedule_sync;
          toast(sy ? (sy.ok ? "Configuration saved · QStash schedules updated" : `Saved, but schedules not updated: ${(sy.errors || [sy.error]).join("; ")}`) : "Configuration saved", sy && !sy.ok ? "err" : "ok", 7000);
          await app.refresh(); drawCfg(); loadOverview();
        }
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

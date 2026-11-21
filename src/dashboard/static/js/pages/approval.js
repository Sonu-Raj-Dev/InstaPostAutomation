import { $, $$, api, badge, busy, confirmDialog, emptyState, html, icon, ist, modal, mount, rel, toast } from "../ui.js";

const TABS = [["PENDING_APPROVAL", "Awaiting approval"], ["PUBLISH_FAILED", "Failed"], ["PUBLISHED", "Published"], ["REJECTED", "Rejected"], ["DRAFT", "Drafts"]];
let off = null;

export default {
  title: "Approval Center",
  eyebrow: "Review · nothing publishes without you",
  async render(view, app) {
    let all = [], tab = "PENDING_APPROVAL", selId = +app.params.get("id") || 0;
    mount(view, html`<div class="tabs" id="tabs" style="margin-bottom:16px"></div><div class="approval"><div class="queue-list" id="qlist"></div><div id="detail"></div></div>`);

    const load = async () => {
      all = await api("/api/carousels");
      if (selId) { const x = all.find((c) => c.id === selId); if (x) tab = x.status === "PUBLISHING" ? "PENDING_APPROVAL" : x.status; }
      draw();
    };
    const draw = () => {
      mount($("#tabs"), html`${TABS.map(([k, l]) => html`<button data-t="${k}" class="${tab === k ? "on" : ""}">${l}<span class="n">${all.filter((c) => c.status === k || (k === "PENDING_APPROVAL" && c.status === "PUBLISHING")).length}</span></button>`)}`);
      const rows = all.filter((c) => c.status === tab || (tab === "PENDING_APPROVAL" && c.status === "PUBLISHING"));
      if (!rows.find((c) => c.id === selId)) selId = rows[0] ? rows[0].id : 0;
      mount($("#qlist"), rows.length ? html`${rows.map((c) => html`<button class="queue-item ${c.id === selId ? "on" : ""}" data-id="${c.id}">
          <div class="th">${c.rendered[0] ? html`<img src="${c.rendered[0]}?v=${encodeURIComponent(c.rendered_at)}" alt="">` : icon("image-off")}</div>
          <div><b>${c.headline}</b><div class="row" style="margin-top:6px;gap:6px">${badge(c.status)}${c.legacy ? html`<span class="chip">legacy</span>` : html`<span class="chip">QC ${c.quality_score}</span>`}</div>
          <div class="dim" style="font-size:11.5px;margin-top:6px">#${c.id} · ${c.slide_count} slide${c.slide_count > 1 ? "s" : ""} · ${rel(c.updated_at || c.created_at)}</div></div></button>`)}`
        : html`<div class="card">${emptyState("inbox", "Nothing here", tab === "PENDING_APPROVAL" ? "Submit a post from the Creator Studio and it will wait here for your approval." : "No posts with this status.", tab === "PENDING_APPROVAL" ? html`<a class="btn sm primary" href="#creator">Open Creator Studio</a>` : "")}</div>`);
      detail(all.find((c) => c.id === selId));
    };

    const detail = (c) => {
      const el = $("#detail");
      if (!c) return mount(el, "");
      const s = app.state, m = s.meta, t = c.topic || {};
      const job = s.running.find((j) => j.kind === "publish");
      const canPublish = ["PENDING_APPROVAL", "PUBLISH_FAILED"].includes(c.status) && !c.legacy;
      const blockers = [];
      if (canPublish && !m.token_valid) blockers.push(html`Instagram is not connected (${m.error ? m.error.slice(0, 90) : "no token"}). <a href="#settings">Reconnect in Settings</a>.`);
      if (canPublish && c.render_stale) blockers.push(html`Slides changed since the last render. <a href="#creator?id=${c.id}">Render in the Studio</a>.`);
      if (canPublish && t.verification_status !== "VERIFIED") blockers.push(html`Source isn't verified. Re-verify it in Daily Intelligence.`);
      const mid = c.ig_media_id || c.metricool_post_id;
      const campaign = (window.__campaigns || []).find((x) => x.carousel_id === c.id || (mid && x.media_id === mid));
      mount(el, html`<div class="card"><div class="card-b stack" style="gap:18px">
        <div class="spread" style="align-items:flex-start"><div>
          <div class="row">${badge(c.status)}<span class="chip">${c.post_format === "SINGLE" ? "Single image" : `${c.slide_count}-slide carousel`}</span>${c.legacy ? "" : html`<span class="chip ${c.qc.passed ? "ok" : "warn"}">QC ${c.quality_score}/100</span>`}${t.category ? html`<span class="chip">${t.category}</span>` : ""}</div>
          <h2 style="font:650 22px/1.2 var(--f-display);letter-spacing:-.02em;margin:12px 0 4px;overflow-wrap:anywhere">${c.headline}</h2>
          <div class="dim" style="font-size:12.5px">Post #${c.id} · created ${ist(c.created_at)}${c.published_at ? html` · published ${ist(c.published_at)}` : ""}</div></div></div>

        ${c.legacy ? html`<div class="notice warn">${icon("history")}<div><b>Created by the previous version.</b> This entry has no per-post slides or verified slide content, so it can't be published from here. Rebuild it from its topic in the Studio, or reject it to clear the queue.</div></div>` : ""}
        ${c.status === "PUBLISHED" ? html`<div class="notice info">${icon("check-circle-2")}<div><b>Published — confirmed by Meta.</b> ${c.ig_media_id || c.metricool_post_id ? html`Media id <span class="mono">${c.ig_media_id || c.metricool_post_id}</span>. ` : ""}${c.permalink && !c.permalink.includes("/p/1") ? html`<a href="${c.permalink}" target="_blank" rel="noopener">Open on Instagram</a>` : html`<span class="dim">No permalink stored.</span>`}</div></div>` : ""}
        ${c.status === "PUBLISH_FAILED" ? html`<div class="notice err">${icon("alert-triangle")}<div><b>Last publish attempt failed${c.publish_stage ? html` during ${c.publish_stage.toLowerCase()}` : ""}.</b><br><span style="overflow-wrap:anywhere">${c.error_message}</span></div></div>` : ""}
        ${c.status === "PUBLISHING" && !(job && job.ref_id === c.id) ? html`<div class="notice warn">${icon("help-circle")}<div><b>Publish not confirmed yet${c.publish_stage ? html` (stopped at ${c.publish_stage.toLowerCase()})` : ""}.</b> ${c.error_message || "The publish request ended without a final answer."} Check status asks Meta whether it went live. It never publishes again.<div style="margin-top:8px"><button class="btn sm" id="recon">${icon("refresh-ccw")}Check status</button></div></div></div>` : ""}
        ${c.status === "REJECTED" && c.reject_reason ? html`<div class="notice">${icon("x-circle")}<div><b>Rejected:</b> ${c.reject_reason}</div></div>` : ""}
        ${job && job.ref_id === c.id || c.status === "PUBLISHING" ? html`<div class="job"><div class="spread"><span class="chip live"><span class="dot"></span>Publishing</span><span class="mono dim">${job ? job.progress : 0}%</span></div><div>${job ? job.stage : "Waiting for Meta…"}</div><div class="progress"><i style="width:${job ? job.progress : 5}%"></i></div></div>` : ""}

        ${c.rendered.length ? html`<div><div class="spread"><div class="label">Slides — rendered JPGs</div>${c.render_stale && !c.legacy ? html`<span class="chip warn">Out of date</span>` : ""}</div>
          <div class="slides-row" style="margin-top:10px">${c.rendered.map((u, i) => html`<button data-lb="${i}" aria-label="Inspect slide ${i + 1}"><img src="${u}?v=${encodeURIComponent(c.rendered_at)}" alt="Slide ${i + 1}" loading="lazy"></button>`)}</div></div>`
          : c.legacy ? "" : html`<div class="notice warn">${icon("image-off")}<div>Not rendered yet. <a href="#creator?id=${c.id}">Render in the Studio</a> to review final images.</div></div>`}

        ${c.legacy ? "" : html`<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr))">
          <div class="stack"><div class="spread"><div class="label">Caption</div><span class="counter" id="cc">${c.caption.length}/2200</span></div>
            <textarea class="textarea" id="cap" style="min-height:200px" ${["PUBLISHED", "PUBLISHING"].includes(c.status) ? "disabled" : ""}>${c.caption}</textarea>
            <div class="label">Hashtags</div><textarea class="textarea mono" id="tags" style="min-height:54px" ${["PUBLISHED", "PUBLISHING"].includes(c.status) ? "disabled" : ""}>${c.hashtags}</textarea>
            ${["PUBLISHED", "PUBLISHING"].includes(c.status) ? "" : html`<button class="btn sm" id="saveCap" style="justify-self:start">${icon("save")}Save caption</button>`}</div>
          <div class="stack">
            <div class="label">Research source</div>
            <dl class="kv"><dt>Original</dt><dd><a href="${t.url}" target="_blank" rel="noopener">${t.url}</a></dd>
              <dt>Verification</dt><dd>${badge(t.verification_status || "UNVERIFIED")} <span class="dim" style="font-size:12px">${t.verification_note}</span></dd>
              <dt>Published</dt><dd>${t.published_date || "—"}</dd><dt>Facts</dt><dd>${(t.facts || []).join(" · ") || "—"}</dd></dl>
            <div class="label">Comment-to-DM</div>
            <dl class="kv"><dt>Keyword</dt><dd><span class="chip info mono">${c.cta_keyword}</span> ${campaign ? html`<a href="#dm?id=${campaign.id}">campaign “${campaign.name}”</a>` : html`<span class="dim">no campaign yet — <a href="#dm">create one after publishing</a></span>`}</dd></dl>
            <div class="label">Resource pack (sent by DM)</div><pre class="pre">${c.resource_pack || "—"}</pre>
          </div></div>`}

        ${c.legacy ? "" : html`<details><summary class="label" style="cursor:pointer">Quality checks (${c.qc.checks ? c.qc.checks.filter((k) => k.pass).length : 0}/${c.qc.checks ? c.qc.checks.length : 0} passed)</summary>
          <div class="checks" style="margin-top:10px">${(c.qc.checks || []).map((k) => html`<div class="check ${k.pass ? "pass" : "fail"}">${icon(k.pass ? "check-circle-2" : "alert-circle")}<div>${k.name}<small>${k.detail}</small></div><span class="pts">${k.points}/${k.max}</span></div>`)}</div></details>`}

        ${c.approved_at && c.scheduled_for && c.status === "PENDING_APPROVAL" ? html`<div class="notice info">${icon("calendar-clock")}<div><b>Approved and scheduled for ${new Date(c.scheduled_for).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" })} IST.</b> It publishes automatically at that time. <button class="btn sm ghost" id="unsched">${icon("calendar-x")}Clear schedule</button></div></div>` : ""}
        ${canPublish && !blockers.length ? html`<div class="row" style="gap:8px;align-items:end"><label class="field" style="margin:0"><span>Publish at (IST)</span><input class="input" type="datetime-local" id="schedAt"></label><button class="btn" id="sched">${icon("calendar-plus")}Approve & schedule</button></div>` : ""}
        ${blockers.length ? html`<div class="notice warn">${icon("lock")}<div><b>Publishing is blocked:</b><ul style="margin:6px 0 0;padding-left:18px">${blockers.map((b) => html`<li>${b}</li>`)}</ul></div></div>` : ""}
        <div class="row">
          ${canPublish ? html`<button class="btn publish" id="pub" ${blockers.length || job ? "disabled" : ""}>${icon("send")}${c.status === "PUBLISH_FAILED" ? "Retry publish" : "Approve & publish"}${m.username ? ` to @${m.username}` : ""}</button>` : ""}
          ${!c.legacy && !["PUBLISHED", "PUBLISHING"].includes(c.status) ? html`<a class="btn" href="#creator?id=${c.id}">${icon("pen-tool")}Edit slides</a><button class="btn" id="regen">${icon("refresh-ccw")}Regenerate</button>` : ""}
          ${c.legacy && c.topic_id ? html`<button class="btn primary" id="rebuild">${icon("sparkles")}Rebuild in Studio</button>` : ""}
          ${!["PUBLISHED", "PUBLISHING", "REJECTED"].includes(c.status) ? html`<button class="btn danger" id="rej">${icon("x")}Reject</button>` : ""}
          ${c.status === "REJECTED" && !c.legacy ? html`<a class="btn" href="#creator?id=${c.id}">${icon("pen-tool")}Revise in Studio</a>` : ""}
        </div></div></div>`);
      bind(c);
    };

    const bind = (c) => {
      $$("[data-lb]").forEach((b) => (b.onclick = () => lightbox(c.rendered.map((u) => `${u}?v=${encodeURIComponent(c.rendered_at)}`), +b.dataset.lb)));
      const cap = $("#cap");
      if (cap) cap.oninput = () => ($("#cc").textContent = cap.value.length + "/2200");
      const sc = $("#saveCap");
      if (sc) sc.onclick = () => busy(sc, async () => {
        try { await api(`/api/carousels/${c.id}`, { method: "PUT", body: { caption: $("#cap").value, hashtags: $("#tags").value } }); toast("Caption saved — post moved back to draft if it was rejected/failed; resubmit if needed", "ok"); await load(); }
        catch (e) { toast(e.message, "err"); }
      });
      const rej = $("#rej");
      if (rej) rej.onclick = async () => {
        const reason = await modal({ title: "Reject this post?", body: html`<label class="field"><span>Reason (helps the next draft)</span><textarea class="textarea" id="why" placeholder="e.g. Weak hook, source too thin, already covered…"></textarea></label>`,
          actions: [{ label: "Cancel", value: null, kind: "ghost" }, { label: "Reject", kind: "danger", value: (root) => root.querySelector("#why").value || "No reason given" }] });
        if (reason == null) return;
        try { await api(`/api/carousels/${c.id}/reject`, { method: "POST", body: { reason } }); toast("Post rejected", "ok"); app.refresh(); await load(); } catch (e) { toast(e.message, "err"); }
      };
      const rg = $("#regen");
      if (rg) rg.onclick = async () => {
        if (!(await confirmDialog("Regenerate this post?", "Slides and caption are rebuilt from the verified research and re-rendered. It returns to Drafts — resubmit from the Studio.", "Regenerate"))) return;
        busy(rg, async () => {
          try {
            await api(`/api/carousels/${c.id}/regenerate`, { method: "POST", body: {} });
            await app.startJob(`/api/carousels/${c.id}/render`, {}, "Render");
            toast("Regenerated and re-rendered", "ok");
            app.go("creator", { id: c.id });
          } catch (e) { toast(e.message, "err"); }
        });
      };
      const rb = $("#rebuild");
      if (rb) rb.onclick = () => busy(rb, async () => { try { const n = await api("/api/carousels", { method: "POST", body: { topic_id: c.topic_id } }); app.go("creator", { id: n.id }); } catch (e) { toast(e.message, "err"); } });
      const sched = $("#sched"), unsched = $("#unsched");
      if (sched) sched.onclick = () => busy(sched, async () => {
        const at = $("#schedAt").value;
        if (!at) return toast("Pick a date and time (IST)", "info");
        try { await api(`/api/carousels/${c.id}/schedule`, { method: "POST", body: { at, confirm: true } }); toast(`Scheduled for ${at.replace("T", " ")} IST`, "ok"); await load(); }
        catch (e) { toast(e.message, "err"); }
      });
      if (unsched) unsched.onclick = () => busy(unsched, async () => {
        try { await api(`/api/carousels/${c.id}/schedule`, { method: "DELETE" }); toast("Schedule cleared", "ok"); await load(); } catch (e) { toast(e.message, "err"); }
      });
      const recon = $("#recon");
      if (recon) recon.onclick = () => busy(recon, async () => {
        try {
          const r = await api(`/api/carousels/${c.id}/reconcile`, { method: "POST" });
          const x = (r.results || [])[0];
          if (!x) toast(r.note, "info", 7000);
          else if (x.result === "published") toast("Meta confirms it's live, marked Published.", "ok", 7000);
          else if (x.result === "failed_safe_to_retry") toast("Meta confirms it did not go live. You can retry safely.", "ok", 7000);
          else toast(`Couldn't confirm yet: ${x.error}`, "err", 9000);
          await load();
        } catch (e) { toast(e.message, "err"); }
      });
      const pub = $("#pub");
      if (pub) pub.onclick = async () => {
        const m = app.state.meta;
        const ok = await modal({ title: "Publish to Instagram?", body: html`<div class="stack">
            <p style="margin:0">This posts <b>${c.slide_count} image${c.slide_count > 1 ? "s" : ""}</b> to <b>@${m.username}</b> immediately via the Meta Graph API. It can't be undone from this app.</p>
            <div class="slides-row" style="grid-template-columns:repeat(5,1fr)">${c.rendered.slice(0, 5).map((u) => html`<button tabindex="-1" style="cursor:default"><img src="${u}?v=${encodeURIComponent(c.rendered_at)}" alt=""></button>`)}</div>
            <pre class="pre" style="max-height:120px">${c.caption}\n\n${c.hashtags}</pre></div>`,
          actions: [{ label: "Cancel", value: false, kind: "ghost" }, { label: `Publish to @${m.username}`, value: true, kind: "publish" }] });
        if (!ok) return;
        try {
          const r = await api(`/api/carousels/${c.id}/publish`, { method: "POST", body: { confirm: true } });
          if (!r.started) return toast(r.error, "err");
          app.refresh(); await load();
          const j = await app.waitJob(r.job_id, () => {});
          const res = JSON.parse(j.result_json || "{}");
          if (j.status === "SUCCESS") toast(html`Published — confirmed by Meta. ${res.permalink ? html`<a href="${res.permalink}" target="_blank" rel="noopener">View post</a>` : ""}`, "ok", 8000);
          else toast(`Publish failed: ${j.error || res.error}`, "err", 9000);
          await load();
        } catch (e) { toast(e.message, "err"); }
      };
    };

    $("#tabs").onclick = (e) => { const b = e.target.closest("[data-t]"); if (b) { tab = b.dataset.t; selId = 0; draw(); } };
    $("#qlist").onclick = (e) => { const b = e.target.closest("[data-id]"); if (b) { selId = +b.dataset.id; draw(); } };
    api("/api/campaigns").then((c) => { window.__campaigns = c; draw(); }).catch(() => {});
    await load();
    let wasRunning = app.state.running.some((j) => j.kind === "publish");
    off = app.on((s) => { const r = s.running.some((j) => j.kind === "publish"); if (wasRunning || r) load(); wasRunning = r; });
  },
  destroy() { off && off(); },
};

function lightbox(urls, i) {
  const lb = document.createElement("div");
  lb.className = "lightbox";
  lb.setAttribute("role", "dialog");
  lb.setAttribute("aria-label", "Slide viewer");
  const show = () => mount(lb, html`<button class="nav-arrow l" data-d="-1" aria-label="Previous">${icon("chevron-left")}</button><img src="${urls[i]}" alt="Slide ${i + 1}"><button class="nav-arrow r" data-d="1" aria-label="Next">${icon("chevron-right")}</button>
    <div style="position:absolute;top:16px;left:50%;transform:translateX(-50%)" class="chip">${i + 1} / ${urls.length}</div><button class="btn icon" data-x style="position:absolute;top:14px;right:14px" aria-label="Close">${icon("x")}</button>`);
  const close = () => { lb.remove(); document.removeEventListener("keydown", key); };
  const key = (e) => { if (e.key === "Escape") close(); if (e.key === "ArrowRight") { i = (i + 1) % urls.length; show(); } if (e.key === "ArrowLeft") { i = (i - 1 + urls.length) % urls.length; show(); } };
  lb.onclick = (e) => {
    const d = e.target.closest("[data-d]");
    if (d) { i = (i + +d.dataset.d + urls.length) % urls.length; show(); }
    else if (e.target === lb || e.target.closest("[data-x]")) close();
  };
  document.addEventListener("keydown", key);
  show();
  document.body.append(lb);
}

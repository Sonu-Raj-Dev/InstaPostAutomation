import { $, api, badge, barList, busy, confirmDialog, emptyState, html, icon, ist, modal, mount, rel, toast } from "../ui.js";

const BLANK = { name: "", keyword: "AGENT", keywords: "", guide_url: "", media_id: "", carousel_id: null, private_reply: "Here's what you asked for 👇", follow_gate: 1,
  follow_gate_message: "Thanks for the comment! Follow the account, then reply DONE here and I'll send the links.", resource_pack: "", public_reply_enabled: 0, public_reply_text: "", active: 0 };
const ORDER = ["RESOURCE_SENT", "AWAITING_TAP", "AWAITING_FOLLOW", "AWAITING_REPLY", "NOT_FOLLOWING", "UNCERTAIN", "FAILED", "SKIPPED_DUPLICATE_USER", "SKIPPED_SELF", "SKIPPED_EXPIRED", "MATCHED", "LEGACY_PROCESSED"];

export default {
  title: "Comment-to-DM",
  eyebrow: "Engage · private replies only",
  async render(view, app) {
    let camps = [], sel = +app.params.get("id") || 0, published = [];
    app.setActions(html`<button class="btn primary" id="newC">${icon("plus")}New campaign</button>`);
    const caps = app.state.meta.capabilities || {};
    mount(view, html`
      <div class="card" style="margin-bottom:16px"><div class="card-b stack">
        <div class="flow">${[["message-square", "Comment with keyword"], ["lock", "1 private reply"], ["user-check", "They reply in DM"], ["search", "Follower lookup"], ["gift", "Resource pack DM"]].map(([i, t], k) => html`${k ? icon("chevron-right") : ""}<span class="row" style="gap:6px">${icon(i)}${t}</span>`)}</div>
        <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px">
          <div class="notice ${caps.messaging ? "info" : "warn"}">${icon(caps.messaging ? "check-circle-2" : "alert-triangle")}<div><b>Messaging permission:</b> ${caps.messaging ? "instagram_manage_messages granted." : app.state.meta.token_valid ? "instagram_manage_messages is NOT on the current token — publishing access does not include messaging." : "unknown — Instagram token is invalid or expired."}</div></div>
          <div class="notice info">${icon("info")}<div><b>Follower status can't be read from a comment.</b> It's only available after the person messages you; until then deliveries show “Awaiting DM reply”.</div></div>
          <div class="notice info">${icon("shield")}<div>One private reply per comment (within 7 days). Follow-ups only inside the 24-hour window after they reply. Public replies stay off unless a campaign enables them.</div></div>
        </div></div></div>
      <div class="dm-grid"><div class="stack" id="clist"></div><div id="editor"></div></div>
      <div class="card" style="margin-top:16px"><div class="card-h"><h3>${icon("activity")}Incoming webhook events</h3><span class="dim" style="font-size:12px">Real events received from Meta (newest first)</span></div>
        <div class="card-b"><div class="table-wrap"><table class="table"><thead><tr><th>Received</th><th>Type</th><th>From</th><th>Text</th><th>Status</th><th></th></tr></thead><tbody id="evs"><tr><td colspan="6"><div class="skel" style="height:40px"></div></td></tr></tbody></table></div></div></div>`);
    const loadEvents = async () => {
      try {
        const r = await api("/api/inbox/events?limit=30");
        mount($("#evs"), r.events.length ? html`${r.events.map((e) => html`<tr><td class="dim" title="${ist(e.received_at)}">${rel(e.received_at)}</td><td>${e.kind}</td><td>${e.sender_username ? "@" + e.sender_username : html`<span class="dim">—</span>`}</td>
            <td style="max-width:280px">${e.text || html`<span class="dim">—</span>`}</td><td>${badge(e.status)}${e.attempts > 1 ? html` <span class="dim" style="font-size:11px">×${e.attempts}</span>` : ""}${e.error ? html`<div style="color:var(--err);font-size:11.5px;margin-top:4px">${e.error.slice(0, 160)}</div>` : ""}</td>
            <td>${e.status === "FAILED" ? html`<button class="btn sm" data-evretry="${e.id}">${icon("refresh-ccw")}Retry</button>` : ""}</td></tr>`)}`
          : html`<tr><td colspan="6">${emptyState("activity", "No webhook events yet", r.app_secret_configured ? "Once Meta is subscribed, every comment on your posts appears here within seconds." : "META_APP_SECRET isn't set, so incoming webhooks are rejected. Add it in Vercel first.")}</td></tr>`);
      } catch (err) { mount($("#evs"), html`<tr><td colspan="6" class="dim">${err.message}</td></tr>`); }
    };
    $("#evs").onclick = (e) => {
      const b = e.target.closest("[data-evretry]");
      if (b) busy(b, async () => { const r = await api(`/api/inbox/events/${b.dataset.evretry}/retry`, { method: "POST" }); toast(r.ok ? "Event re-queued" : r.error, r.ok ? "ok" : "err"); loadEvents(); });
    };
    loadEvents();

    const load = async () => {
      [camps, published] = await Promise.all([api("/api/campaigns"), api("/api/carousels?status=PUBLISHED")]);
      if (!camps.find((c) => c.id === sel)) sel = camps[0] ? camps[0].id : 0;
      drawList();
      sel ? edit(camps.find((c) => c.id === sel)) : edit(null);
    };
    const drawList = () => mount($("#clist"), camps.length ? html`${camps.map((c) => html`<button class="queue-item ${c.id === sel ? "on" : ""}" data-id="${c.id}" style="grid-template-columns:1fr">
        <div><div class="spread"><b>${c.name}</b>${c.active ? html`<span class="chip live"><span class="dot"></span>Active</span>` : html`<span class="chip">Paused</span>`}</div>
        <div class="row" style="margin-top:8px;gap:6px">${[c.keyword, ...(c.keywords ? c.keywords.split(",") : [])].map((k) => html`<span class="chip info mono">${k}</span>`)}<span class="dim" style="font-size:12px">${c.stats.RESOURCE_SENT || 0} sent · ${c.stats.AWAITING_REPLY || 0} waiting · ${c.stats.FAILED || 0} failed</span></div></div></button>`)}`
      : html`<div class="card">${emptyState("message-circle-heart", "No campaigns", "Create a campaign for a published post: keyword → private reply → resource pack.")}</div>`);

    const edit = async (c) => {
      const isNew = !c, d = c || { ...BLANK };
      const stats = (c && c.stats) || {};
      const total = Object.values(stats).reduce((a, b) => a + b, 0);
      mount($("#editor"), html`<div class="card"><div class="card-b stack" style="gap:18px">
        ${c ? html`<div class="stat-row">${[["Matched", total], ["Resource sent", stats.RESOURCE_SENT || 0], ["Awaiting reply", stats.AWAITING_REPLY || 0], ["Not following", stats.NOT_FOLLOWING || 0], ["Failed", stats.FAILED || 0]].map(([l, v]) => html`<div class="mini"><span class="label">${l}</span><b>${v}</b></div>`)}</div>` : ""}
        <form class="stack" id="cform" style="gap:14px" novalidate>
          <div class="grid" style="grid-template-columns:2fr 1fr">
            <label class="field"><span>Campaign name</span><input class="input" name="name" value="${d.name}" required maxlength="80" placeholder="e.g. Concat repo pack"></label>
            <label class="field"><span>Trigger keyword</span><input class="input mono" name="keyword" value="${d.keyword}" required maxlength="20" placeholder="AGENT"></label></div>
          <div class="grid" style="grid-template-columns:1fr 1fr">
            <label class="field"><span>Extra keywords</span><input class="input mono" name="keywords" value="${d.keywords || ""}" maxlength="220" placeholder="GUIDE, LINK"><small>Comma separated. Case doesn't matter: agent = AGENT.</small></label>
            <label class="field"><span>Guide link</span><input class="input" name="guide_url" value="${d.guide_url || ""}" maxlength="500" placeholder="https://…"><small>Added to the guide DM. Use {guide_url} in messages to place it yourself.</small></label></div>
          <div class="row" style="gap:6px"><span class="dim" style="font-size:12px">Ideas:</span>${["AGENT", "REPO", "VIDEO", "EDIT", "PROMPT"].map((k) => html`<button type="button" class="chip" data-kw="${k}" style="cursor:pointer">${k}</button>`)}</div>
          <div class="grid" style="grid-template-columns:1fr 1fr">
            <label class="field"><span>Associated post</span><select class="select" name="carousel_id"><option value="">— Manual media id —</option>${published.filter((p) => p.ig_media_id || p.metricool_post_id).map((p) => html`<option value="${p.id}" ${d.carousel_id === p.id ? "selected" : ""}>#${p.id} · ${p.headline.slice(0, 48)}</option>`)}</select></label>
            <label class="field"><span>Instagram media id</span><input class="input mono" name="media_id" value="${d.media_id}" placeholder="1790…"><small>Filled automatically when you pick a post.</small></label></div>
          <label class="field"><span>Private reply (opening line)</span><textarea class="textarea" name="private_reply" maxlength="1000">${d.private_reply}</textarea></label>
          <label class="row" style="justify-content:space-between"><span><b style="font-weight:600">Follow gate</b><br><span class="dim" style="font-size:12px">Ask them to follow & reply first; resource sent only if the profile lookup shows they follow</span></span><span class="switch"><input type="checkbox" name="follow_gate" ${d.follow_gate ? "checked" : ""}><i></i></span></label>
          <label class="field"><span>Follow-gate message</span><textarea class="textarea" name="follow_gate_message" maxlength="1000">${d.follow_gate_message}</textarea></label>
          <label class="field"><span>Resource package <button type="button" class="btn sm ghost" id="fillPack">${icon("download")}Fill from post</button></span><textarea class="textarea mono" name="resource_pack" style="min-height:120px" maxlength="1000" placeholder="Exact prompt, repo links and steps for THIS post">${d.resource_pack}</textarea></label>
          <label class="row" style="justify-content:space-between"><span><b style="font-weight:600">Public comment reply</b><br><span class="dim" style="font-size:12px">Off = private messages only (recommended)</span></span><span class="switch"><input type="checkbox" name="public_reply_enabled" ${d.public_reply_enabled ? "checked" : ""}><i></i></span></label>
          <label class="field" id="pubText" ${d.public_reply_enabled ? "" : "hidden"}><span>Public reply text</span><input class="input" name="public_reply_text" value="${d.public_reply_text}" maxlength="200" placeholder="Sent you a DM 📩"></label>
          <label class="row" style="justify-content:space-between"><span><b style="font-weight:600">Active</b><br><span class="dim" style="font-size:12px">Allows live scans to send messages</span></span><span class="switch"><input type="checkbox" name="active" ${d.active ? "checked" : ""}><i></i></span></label>
          <div class="row"><button class="btn primary" type="submit">${icon("save")}${isNew ? "Create campaign" : "Save campaign"}</button>
            ${c ? html`<button type="button" class="btn" id="dry">${icon("scan-eye")}Preview scan (no messages)</button><button type="button" class="btn danger" id="live" ${c.active ? "" : "disabled title='Activate the campaign first'"}>${icon("send")}Run live scan</button>` : ""}</div>
        </form>
        ${c ? html`<div><div class="label" style="margin-bottom:10px">Delivery breakdown</div>${barList(ORDER.filter((k) => stats[k]).map((k) => ({ label: k.replace(/_/g, " ").toLowerCase(), value: stats[k] })))}</div>
          <div><div class="label" style="margin-bottom:10px">Deliveries</div><div class="table-wrap"><table class="table"><thead><tr><th>User</th><th>Comment</th><th>Status</th><th>Follower</th><th>Updated</th><th></th></tr></thead><tbody id="dl"><tr><td colspan="6"><div class="skel" style="height:40px"></div></td></tr></tbody></table></div></div>` : ""}
      </div></div>`);
      const f = $("#cform");
      f.onclick = (e) => { const k = e.target.closest("[data-kw]"); if (k) f.keyword.value = k.dataset.kw; };
      f.public_reply_enabled.onchange = () => ($("#pubText").hidden = !f.public_reply_enabled.checked);
      f.carousel_id.onchange = () => { const p = published.find((x) => x.id === +f.carousel_id.value); if (p) f.media_id.value = p.ig_media_id || p.metricool_post_id; };
      $("#fillPack").onclick = () => {
        const p = published.find((x) => x.id === +f.carousel_id.value);
        if (!p) return toast("Pick an associated post first", "info");
        f.resource_pack.value = p.resource_pack || "";
        if (p.cta_keyword) f.keyword.value = p.cta_keyword;
      };
      f.onsubmit = async (e) => {
        e.preventDefault();
        const body = { name: f.name.value.trim(), keyword: f.keyword.value.trim(), keywords: f.keywords.value.trim(), guide_url: f.guide_url.value.trim(), media_id: f.media_id.value.trim(), carousel_id: f.carousel_id.value ? +f.carousel_id.value : null,
          private_reply: f.private_reply.value, follow_gate: f.follow_gate.checked, follow_gate_message: f.follow_gate_message.value, resource_pack: f.resource_pack.value,
          public_reply_enabled: f.public_reply_enabled.checked, public_reply_text: f.public_reply_text.value, active: f.active.checked };
        if (!body.name || !body.keyword) return toast("Name and keyword are required", "err");
        if (!body.resource_pack.trim()) return toast("Add the resource package this campaign delivers", "err");
        if (body.public_reply_enabled && !body.public_reply_text.trim()) return toast("Write the public reply text or turn public replies off", "err");
        await busy(f.querySelector("[type=submit]"), async () => {
          try {
            const r = await api(isNew ? "/api/campaigns" : `/api/campaigns/${c.id}`, { method: isNew ? "POST" : "PUT", body });
            sel = r.id; toast(isNew ? "Campaign created" : "Campaign saved", "ok"); await load(); app.refresh();
          } catch (err) { toast(err.message, "err"); }
        });
      };
      if (!c) return;
      api(`/api/campaigns/${c.id}/deliveries`).then((rows) => mount($("#dl"), rows.length ? html`${rows.map((r) => html`<tr><td>${r.username ? "@" + r.username : html`<span class="dim">—</span>`}</td><td style="max-width:260px">${r.comment_text || html`<span class="dim mono">${r.comment_id}</span>`}</td><td>${badge(r.status)}${r.error ? html`<div style="color:var(--err);font-size:11.5px;margin-top:4px">${r.error.slice(0, 140)}</div>` : ""}</td><td>${r.follower_status}</td><td class="dim">${rel(r.updated_at || r.created_at)}</td>
          <td style="white-space:nowrap"><button class="btn sm ghost" data-log="${r.id}">${icon("history")}History</button>${["FAILED", "UNCERTAIN"].includes(r.status) ? html`<button class="btn sm" data-retry="${r.id}" data-st="${r.status}">${icon("refresh-ccw")}Retry</button>` : ""}</td></tr>`)}`
        : html`<tr><td colspan="6">${emptyState("inbox", "No deliveries yet", "Run a preview scan to see which comments match.")}</td></tr>`));
      $("#dl").onclick = async (e) => {
        const lg = e.target.closest("[data-log]"), rt = e.target.closest("[data-retry]");
        if (lg) {
          const rows = await api(`/api/deliveries/${lg.dataset.log}/log`);
          return modal({ title: "Delivery history", body: rows.length ? html`<table class="table"><thead><tr><th>When (UTC)</th><th>Step</th><th>Result</th></tr></thead><tbody>${rows.map((x) => html`<tr><td class="mono dim">${x.at.replace("T", " ").replace("Z", "")}</td><td>${x.step.replace(/_/g, " ")}</td><td>${x.ok ? badge("OK") : badge("FAILED")} <span style="font-size:12px">${x.detail}</span></td></tr>`)}</tbody></table>` : html`<p class="dim">No history recorded for this delivery (it predates delivery history).</p>` });
        }
        if (rt) {
          const unc = rt.dataset.st === "UNCERTAIN";
          if (!(await confirmDialog("Retry this private reply?", unc ? "Meta never confirmed the first attempt, so this person MAY already have it. Retrying could send a second message." : "Sends one private reply for this comment again. Meta allows replies only within 7 days of the comment.", "Retry", unc ? "danger" : "primary"))) return;
          await busy(rt, async () => {
            const r = await api(`/api/deliveries/${rt.dataset.retry}/retry`, { method: "POST", body: { confirm_uncertain: unc } });
            toast(r.ok ? "Private reply sent" : `Retry failed: ${r.error}`, r.ok ? "ok" : "err", 9000);
            await load();
          });
        }
      };
      const scan = async (live, btn) => {
        await busy(btn, async () => {
          try {
            const r = await api(`/api/campaigns/${c.id}/scan`, { method: "POST", body: { live, confirm: live, wait: true } });
            const j = await api(`/api/jobs/${r.job_id}`);
            const res = JSON.parse(j.result_json || "{}");
            if (j.status !== "SUCCESS") return toast(`Scan failed: ${j.error || res.error}`, "err", 9000);
            await modal({ title: live ? "Live scan finished" : "Preview — nothing was sent", body: html`<p style="margin-top:0">${res.comments_read} comments read · ${res.matches.length} new keyword matches${res.followups.length ? ` · ${res.followups.length} awaiting-reply checks` : ""}.</p>
              ${res.matches.length ? html`<table class="table"><thead><tr><th>User</th><th>Comment</th><th>${live ? "Result" : "Would do"}</th></tr></thead><tbody>${res.matches.map((m) => html`<tr><td>@${m.username}</td><td>${m.text}</td><td>${live ? badge(m.status) : m.action}${m.error ? html`<div style="color:var(--err);font-size:11.5px">${m.error}</div>` : ""}</td></tr>`)}</tbody></table>` : html`<p class="dim">No new matching comments.</p>`}` });
            await load();
          } catch (err) { toast(err.message, "err", 9000); }
        });
      };
      $("#dry").onclick = (e) => scan(false, e.currentTarget);
      $("#live").onclick = async (e) => {
        if (!(await confirmDialog("Send private replies now?", `New comments containing “${c.keyword}” on media ${c.media_id} get ONE private reply each${c.follow_gate ? " (follow-gate message)" : " with the resource pack"}. People who already received one are skipped.`, "Send replies", "danger"))) return;
        scan(true, e.currentTarget);
      };
    };

    $("#clist").onclick = (e) => { const b = e.target.closest("[data-id]"); if (b) { sel = +b.dataset.id; drawList(); edit(camps.find((c) => c.id === sel)); } };
    $("#newC").onclick = () => { sel = 0; drawList(); edit(null); };
    await load();
  },
};

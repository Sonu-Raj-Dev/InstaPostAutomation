import { $, $$, api, busy, html, icon, ist, mount, num, toast } from "../ui.js";

const CAP = { publish: "Publish content", insights: "Read insights", comments: "Manage comments", messaging: "Send messages" };

export default {
  title: "Settings & Integrations",
  eyebrow: "Settings · credentials stay on this machine",
  async render(view, app) {
    mount(view, html`<div class="settings-grid">
      <div class="card" style="grid-column:1/-1"><div class="card-h"><h3>${icon("instagram")}Instagram connection</h3><button class="btn sm" id="diag">${icon("stethoscope")}Run diagnostics</button></div><div class="card-b" id="conn"><div class="skel" style="height:120px"></div></div></div>
      <div class="card" style="grid-column:1/-1"><div class="card-h"><h3>${icon("message-circle-heart")}Comment auto-reply</h3><span class="dim" style="font-size:12px" id="dmState"></span></div><div class="card-b"><form class="stack" id="dmf" novalidate></form></div></div>
      <div class="card"><div class="card-h"><h3>${icon("palette")}Visual identity & defaults</h3></div><div class="card-b"><form class="stack" id="ident" novalidate></form></div></div>
      <div class="card"><div class="card-h"><h3>${icon("cpu")}Engines, research & cost controls</h3></div><div class="card-b stack" id="sys"><div class="skel" style="height:160px"></div></div></div>
    </div>`);

    const drawConn = (d) => {
      const tk = d.token || {}, a = d.account || {};
      const exp = tk.expires_at ? (tk.expires_at === 0 ? "Never" : ist(tk.expires_at)) : "—";
      mount($("#conn"), html`<div class="stack" style="gap:16px">
        ${d.token_valid ? html`<div class="notice info">${icon("check-circle-2")}<div><b>Connected as @${a.username}</b> (${a.name || ""}) · Instagram account id <span class="mono">${d.account_id}</span>. Only this account is ever published to.</div></div>`
          : html`<div class="notice err">${icon("plug-zap")}<div><b>Not connected.</b> ${d.error || "No token configured."}</div></div>`}
        <div class="diag">
          <div class="mini"><span class="label">Token</span><b style="font-size:16px">${d.token_valid ? "Valid" : "Invalid"}</b><div class="dim" style="font-size:12px">${tk.type || ""}</div></div>
          <div class="mini"><span class="label">Expires</span><b style="font-size:16px">${exp}</b><div class="dim" style="font-size:12px">${tk.data_access_expires_at ? "data access until " + ist(tk.data_access_expires_at, { dateStyle: "medium" }) : ""}</div></div>
          <div class="mini"><span class="label">Followers</span><b style="font-size:16px">${num(a.followers_count)}</b><div class="dim" style="font-size:12px">${num(a.media_count)} posts</div></div>
          <div class="mini"><span class="label">Permissions</span><div class="row" style="margin-top:8px;gap:6px">${Object.entries(CAP).map(([k, l]) => html`<span class="chip ${d.capabilities && d.capabilities[k] ? "ok" : ""}" title="${k}">${l}</span>`)}</div></div>
        </div>
        ${(tk.scopes || []).length ? html`<div class="row" style="gap:6px"><span class="label">Scopes</span>${tk.scopes.map((s) => html`<span class="chip mono" style="font-size:11px">${s}</span>`)}</div>` : ""}
        <form id="tokForm" class="stack" style="gap:10px;max-width:760px" autocomplete="off">
          <div class="label">Renew access token</div>
          <p class="muted" style="margin:0;font-size:13px">Generate a user token in Meta's Graph API Explorer for your app with <span class="mono">instagram_basic, instagram_content_publish, instagram_manage_insights, instagram_manage_comments, instagram_manage_messages, pages_show_list, pages_read_engagement</span>. Paste it here: it's exchanged for a 60-day token when the app secret is configured, checked against account <span class="mono">${d.account_id}</span>, and saved to <span class="mono">.env</span> only if it can access that exact account. The token is never shown again.</p>
          <div class="row" style="flex-wrap:nowrap"><input class="input mono" type="password" name="token" placeholder="Paste short-lived token" aria-label="Short-lived access token" style="flex:1"><button class="btn primary" type="submit">${icon("key-round")}Exchange & save</button></div>
        </form></div>`);
      $("#tokForm").onsubmit = async (e) => {
        e.preventDefault();
        const f = e.target, v = f.token.value.trim();
        if (v.length < 50) return toast("That doesn't look like a Graph API token", "err");
        await busy(f.querySelector("button"), async () => {
          try {
            const r = await api("/api/meta/token", { method: "POST", body: { token: v } });
            f.reset();
            toast(r.exchanged ? `Token exchanged for @${r.username} — valid ~${Math.round((r.expires_in || 0) / 86400)} days` : `Token saved for @${r.username}${r.expires_at ? " — expires " + ist(r.expires_at) : ""} (not exchanged: no app secret)`, "ok", 9000);
            await app.refresh("?refresh_meta=true");
            drawConn(await api("/api/meta/diagnostics"));
          } catch (err) { f.token.value = ""; toast(err.message, "err", 9000); }
        });
      };
    };

    const s = app.state.settings;
    mount($("#ident"), html`
      <div class="grid" style="grid-template-columns:1fr 1fr">
        <label class="field" data-f="brand_name"><span>Brand name</span><input class="input" name="brand_name" value="${s.brand_name}" maxlength="40"></label>
        <label class="field" data-f="creator_handle"><span>Handle on slides</span><input class="input" name="creator_handle" value="${s.creator_handle}" maxlength="31"></label></div>
      <div class="grid" style="grid-template-columns:1fr 1fr">
        <label class="field" data-f="default_theme"><span>Default slide theme</span><select class="select" name="default_theme">${["studio", "midnight", "paper", "signal"].map((t) => html`<option ${s.default_theme === t ? "selected" : ""}>${t}</option>`)}</select></label>
        <label class="field" data-f="default_accent"><span>Default accent</span><div class="row" style="flex-wrap:nowrap"><input type="color" name="default_accent_picker" value="${s.default_accent}" aria-label="Pick accent"><input class="input mono" name="default_accent" value="${s.default_accent}" maxlength="7"></div></label></div>
      <div class="grid" style="grid-template-columns:1fr 2fr">
        <label class="field" data-f="default_cta_keyword"><span>Default comment keyword</span><input class="input mono" name="default_cta_keyword" value="${s.default_cta_keyword}" maxlength="20"></label>
        <label class="field" data-f="default_hashtags"><span>Default hashtags</span><input class="input mono" name="default_hashtags" value="${s.default_hashtags}"></label></div>
      <label class="field" data-f="max_research_items"><span>Max new stories per research run <small>cost & noise control</small></span><input class="input" type="number" min="5" max="100" name="max_research_items" value="${s.max_research_items}"></label>
      <div class="row"><button class="btn primary" type="submit">${icon("save")}Save settings</button><a class="btn ghost" href="#automation">${icon("workflow")}Schedule & mode →</a></div>`);
    const dmf = $("#dmf");
    mount(dmf, html`<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr))">
        <label class="row" style="justify-content:space-between"><span><b style="font-weight:600">Auto-reply to comments</b><br><span class="dim" style="font-size:12px">Every published post gets it automatically</span></span><span class="switch"><input type="checkbox" name="auto_dm" ${s.auto_dm === "1" ? "checked" : ""}><i></i></span></label>
        <label class="row" style="justify-content:space-between"><span><b style="font-weight:600">Only send to followers</b><br><span class="dim" style="font-size:12px">Non-followers get the “follow first” message + button</span></span><span class="switch"><input type="checkbox" name="dm_follow_gate" ${s.dm_follow_gate === "1" ? "checked" : ""}><i></i></span></label>
        <label class="field" data-f="dm_poll_minutes"><span>Check comments every (minutes)</span><input class="input" type="number" min="1" max="60" name="dm_poll_minutes" value="${s.dm_poll_minutes || 2}"></label></div>
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">
        <label class="field" data-f="dm_opener"><span>First message (with button “Send me the access”)</span><textarea class="textarea" name="dm_opener">${s.dm_opener || ""}</textarea></label>
        <label class="field" data-f="dm_not_following"><span>If they don't follow yet (with button “I'm following ✅”)</span><textarea class="textarea" name="dm_not_following">${s.dm_not_following || ""}</textarea></label></div>
      <div class="row"><button class="btn primary" type="submit">${icon("save")}Save auto-reply</button><span class="dim" style="font-size:12px">The guide (text + guide pages) is built from each post automatically.</span></div>`);
    const dmst = app.state.dm;
    $("#dmState").textContent = dmst.last_error ? `Last check failed: ${dmst.last_error}` : dmst.last_poll ? `${dmst.active} active · last check ${new Date(dmst.last_poll).toLocaleTimeString()}` : `${dmst.active} active`;
    dmf.onsubmit = async (e) => {
      e.preventDefault();
      const body = { auto_dm: dmf.auto_dm.checked ? "1" : "0", dm_follow_gate: dmf.dm_follow_gate.checked ? "1" : "0", dm_poll_minutes: dmf.dm_poll_minutes.value, dm_opener: dmf.dm_opener.value.trim(), dm_not_following: dmf.dm_not_following.value.trim() };
      await busy(dmf.querySelector("[type=submit]"), async () => {
        try { await api("/api/settings", { method: "POST", body }); toast("Auto-reply saved", "ok"); app.refresh(); }
        catch (err) { toast(err.fields ? "Messages need 5–600 characters; minutes 1–60" : err.message, "err"); }
      });
    };
    const f = $("#ident");
    f.default_accent_picker.oninput = () => (f.default_accent.value = f.default_accent_picker.value.toUpperCase());
    f.onsubmit = async (e) => {
      e.preventDefault();
      $$(".field", f).forEach((x) => { x.classList.remove("bad"); const er = x.querySelector(".err"); er && er.remove(); });
      const body = Object.fromEntries(["brand_name", "creator_handle", "default_theme", "default_accent", "default_cta_keyword", "default_hashtags", "max_research_items"].map((k) => [k, f[k].value.trim()]));
      body.default_cta_keyword = body.default_cta_keyword.toUpperCase();
      await busy(f.querySelector("[type=submit]"), async () => {
        try { await api("/api/settings", { method: "POST", body }); toast("Settings saved", "ok"); app.refresh(); }
        catch (err) {
          if (!err.fields) return toast(err.message, "err");
          Object.entries(err.fields).forEach(([k, m]) => { const x = f.querySelector(`[data-f="${k}"]`); if (x) { x.classList.add("bad"); x.insertAdjacentHTML("beforeend", `<span class="err">${m}${k === "creator_handle" ? " — use @name" : k === "default_hashtags" ? " — every tag must start with #" : ""}</span>`); } });
          toast("Fix the highlighted fields", "err");
        }
      });
    };

    api("/api/system").then((x) => {
      const gl = x.github_search_limit;
      mount($("#sys"), html`
        <dl class="kv">
          <dt>Slide renderer</dt><dd>${x.browser ? html`<span class="chip ok">Headless browser</span> <span class="dim mono" style="font-size:11.5px">${x.browser}</span>` : html`<span class="chip err">Missing</span> Install Edge or Chrome, or set CMS_BROWSER.`}</dd>
          <dt>Copywriting</dt><dd>${x.llm_configured ? "ANTHROPIC_API_KEY present (not used by the current engine)" : "Deterministic templates from verified research fields — no AI model configured, so no API cost and no invented claims."}</dd>
          <dt>GitHub API</dt><dd>${x.github_token ? html`<span class="chip ok">Token set</span>` : html`<span class="chip warn">No GITHUB_TOKEN</span> <span class="dim">unauthenticated: 10 searches/min</span>`}${gl ? html` · ${gl.remaining}/${gl.limit} search calls left this minute` : ""}</dd>
          <dt>Meta app</dt><dd>${x.meta_app_id && x.meta_app_secret ? "App id & secret configured — pasted tokens are exchanged for 60-day tokens"
            : html`<span class="chip warn">${!x.meta_app_id ? "META_APP_ID" : "META_APP_SECRET"} is empty in .env</span> <span class="dim">Pasted tokens are saved as issued (no 60-day exchange). Add the app secret from developers.facebook.com → App settings → Basic to enable exchange.</span>`}</dd>
          <dt>Publishing target</dt><dd class="mono">${x.account_id || "—"} <span class="dim" style="font-family:var(--f-body)">(INSTAGRAM_ACCOUNT_ID in .env — not editable here)</span></dd>
          <dt>Storage</dt><dd class="mono" style="font-size:12px">${x.db}</dd>
        </dl>
        <div class="notice">${icon("lock")}<div>Secrets live only in <span class="mono">.env</span>. The UI and API never return token values.</div></div>`);
    });

    drawConn(await api("/api/meta/diagnostics"));
    $("#diag").onclick = (e) => busy(e.currentTarget, async () => { drawConn(await api("/api/meta/diagnostics")); app.refresh(); toast("Diagnostics refreshed", "info"); });
  },
};

import { $, $$, api, barList, compact, emptyState, html, icon, ist, lineChart, mount, num, toast } from "../ui.js";

const FORMAT = { CAROUSEL_ALBUM: "Carousel", VIDEO: "Reel / video", IMAGE: "Single image" };

export default {
  title: "Analytics",
  eyebrow: "Measure · Instagram Graph API",
  async render(view, app) {
    let days = +app.params.get("days") || 30;
    app.setActions(html`<div class="seg" id="range">${[7, 14, 30].map((d) => html`<button data-d="${d}" class="${d === days ? "on" : ""}">${d} days</button>`)}</div><button class="btn" id="refresh">${icon("refresh-cw")}Refresh</button>`);
    const load = async (refresh = false) => {
      mount(view, html`<div class="kpis">${[1, 2, 3, 4, 5, 6].map(() => html`<div class="skel" style="height:104px;border-radius:16px"></div>`)}</div><div class="skel" style="height:300px;margin-top:16px;border-radius:16px"></div>`);
      let d;
      try { d = await api(`/api/analytics?days=${days}${refresh ? "&refresh=true" : ""}`); } catch (e) { d = { success: false, error: e.message }; }
      if (!d.success) {
        return mount(view, html`<div class="card"><div class="card-b">${emptyState("plug-zap", "Instagram isn't connected", html`Analytics only show real numbers from Meta — nothing is estimated or filled in.<br><span class="dim" style="font-size:12px">${d.error || ""}</span>`, html`<a class="btn primary sm" href="#settings">Reconnect Instagram</a>`)}
          <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin-top:10px">${["Reach & views per day", "Follower growth (30 days)", "Likes, comments, saves, shares", "Post-level performance", "Category performance", "Carousel vs Reel"].map((x) => html`<div class="mini"><span class="label">Available once connected</span><div style="margin-top:6px">${x}</div></div>`)}</div></div></div>`);
      }
      const t = d.totals || {}, media = d.media || [];
      const eng = (m) => (m.insights && m.insights.total_interactions) ?? (m.like_count || 0) + (m.comments_count || 0);
      const kpi = (l, v, sub = "") => html`<div class="card kpi"><div class="label">${l}</div><div class="v">${v == null ? "—" : compact(v)}</div><div class="d">${sub}</div></div>`;
      const reach = (d.series.reach || []);
      const fol = (d.series.follower_count || []);
      const byCat = {}, byFmt = {};
      media.forEach((m) => {
        const e = eng(m);
        (byCat[m.category] = byCat[m.category] || []).push(e);
        const f = FORMAT[m.media_type] || m.media_type;
        (byFmt[f] = byFmt[f] || []).push(e);
      });
      const avg = (o) => Object.entries(o).map(([k, v]) => ({ label: `${k} (${v.length})`, value: Math.round(v.reduce((a, b) => a + b, 0) / v.length) })).sort((a, b) => b.value - a.value);
      mount(view, html`
        ${d.errors.length ? html`<div class="notice warn" style="margin-bottom:16px">${icon("alert-triangle")}<div><b>Some metrics were unavailable from Meta:</b> ${d.errors.map((e) => e.slice(0, 140)).join(" · ")}</div></div>` : ""}
        <div class="kpis" style="margin-top:0">
          ${kpi("Followers", d.account && d.account.followers_count, `@${d.account ? d.account.username : ""}`)}
          ${kpi("Reach", reach.reduce((a, b) => a + b.value, 0) || t.reach, `last ${days} days`)}
          ${kpi("Views", t.views, `last ${days} days`)}
          ${kpi("Interactions", t.total_interactions, `${num(t.likes)} likes · ${num(t.comments)} comments`)}
          ${kpi("Saves", t.saves, "bookmark intent")}
          ${kpi("Shares", t.shares, `${num(t.profile_views)} profile views`)}
        </div>
        <div class="an-grid">
          <div class="card"><div class="card-h"><h3>${icon("trending-up")}Daily reach</h3></div><div class="card-b">${lineChart(reach, { color: "#4C7DFF" })}</div></div>
          <div class="card"><div class="card-h"><h3>${icon("users")}New followers / day</h3></div><div class="card-b">${fol.length ? lineChart(fol, { color: "#8B5CF6", h: 260 }) : emptyState("users", "No follower data", "Meta only reports follower_count for accounts with 100+ followers, for the last 30 days.")}</div></div>
        </div>
        <div class="an-grid">
          <div class="card"><div class="card-h"><h3>${icon("table")}Post performance</h3><span class="dim" style="font-size:12px">${media.length} recent posts</span></div><div class="card-b"><div class="table-wrap"><table class="table">
            <thead><tr><th>Post</th><th>Format</th><th>Reach</th><th>Views</th><th>Likes</th><th>Comments</th><th>Saves</th><th>Shares</th></tr></thead>
            <tbody>${media.length ? media.map((m) => html`<tr><td style="max-width:280px"><a href="${m.permalink}" target="_blank" rel="noopener">${(m.caption || "(no caption)").split("\n")[0].slice(0, 60)}</a><div class="dim" style="font-size:11.5px">${ist(m.timestamp)} · ${m.category}</div></td>
              <td>${FORMAT[m.media_type] || m.media_type}</td><td class="mono">${num(m.insights.reach)}</td><td class="mono">${num(m.insights.views)}</td><td class="mono">${num(m.like_count)}</td><td class="mono">${num(m.comments_count)}</td><td class="mono">${num(m.insights.saved)}</td><td class="mono">${num(m.insights.shares)}</td></tr>`)
              : html`<tr><td colspan="8">${emptyState("image", "No posts", "Nothing published on this account yet.")}</td></tr>`}</tbody></table></div></div></div>
          <div class="stack" style="gap:16px">
            <div class="card"><div class="card-h"><h3>${icon("shapes")}Carousel vs Reel</h3></div><div class="card-b"><div class="dim" style="font-size:12px;margin-bottom:10px">Average interactions per post</div>${barList(avg(byFmt))}</div></div>
            <div class="card"><div class="card-h"><h3>${icon("tags")}By content category</h3></div><div class="card-b"><div class="dim" style="font-size:12px;margin-bottom:10px">Average interactions · posts created here are tagged with their research category</div>${barList(avg(byCat))}</div></div>
          </div>
        </div>`);
    };
    $("#range").onclick = (e) => { const b = e.target.closest("[data-d]"); if (b) { days = +b.dataset.d; $$("#range button").forEach((x) => x.classList.toggle("on", x === b)); load(); } };
    $("#refresh").onclick = () => load(true).then(() => toast("Analytics refreshed from Meta", "ok"));
    await load();
  },
};

// My posts — everything you've made, what state it's in, and how its DM auto-reply is doing.
import { $, api, badge, emptyState, html, icon, mount, rel, toast } from "../ui.js";

const GROUPS = [["Published", (c) => c.status === "PUBLISHED"], ["Ready to publish", (c) => ["PENDING_APPROVAL", "PUBLISH_FAILED", "PUBLISHING"].includes(c.status)],
  ["Drafts", (c) => ["DRAFT", "REJECTED"].includes(c.status)]];

export default {
  title: "My posts",
  eyebrow: "Posts · auto-replies",
  async render(view, app) {
    app.setActions(html`<a class="btn primary" href="#create">${icon("plus")}Create post</a>`);
    const load = async () => {
      const [cars, camps] = await Promise.all([api("/api/carousels"), api("/api/campaigns")]);
      const list = cars.filter((c) => !c.legacy);
      const dm = app.state.dm;
      mount(view, html`
        ${dm.last_error ? html`<div class="notice warn" style="margin-bottom:16px">${icon("alert-triangle")}<div><b>Auto-reply can't read comments right now.</b> ${dm.last_error} — <a href="#settings">check the Instagram connection</a>.</div></div>` : ""}
        ${list.length ? GROUPS.map(([label, f]) => {
          const rows = list.filter(f);
          return rows.length ? html`<h2 class="h2" style="margin:8px 0 12px">${label} <span class="dim" style="font-size:14px">${rows.length}</span></h2>
            <div class="post-list">${rows.map((c) => row(c, camps.find((k) => k.carousel_id === c.id)))}</div>` : "";
        }) : html`<div class="card">${emptyState("image-plus", "No posts yet", "Create your first post in 3 steps.", html`<a class="btn primary sm" href="#create">Create post</a>`)}</div>`}`);
    };
    const row = (c, k) => {
      const st = (k && k.stats) || {};
      const cover = c.rendered[0] ? html`<img src="${c.rendered[0]}?v=${encodeURIComponent(c.rendered_at)}" alt="">` : html`<iframe title="cover" src="/api/carousels/${c.id}/slides/1.html" style="width:1080px;height:1350px;border:0;transform:scale(${84 / 1080});transform-origin:0 0;pointer-events:none"></iframe>`;
      const next = c.status === "PUBLISHED" ? "" : html`<a class="btn sm primary" href="#create?id=${c.id}&step=${c.render_stale ? 2 : 3}">${c.render_stale ? "Continue" : "Publish"}</a>`;
      return html`<div class="card post-row"><div class="post-cover">${cover}</div>
        <div class="post-main"><b>${c.headline}</b>
          <div class="row" style="gap:6px;margin-top:8px">${badge(c.status)}<span class="chip">${c.slide_count} slides</span><span class="chip info mono">${c.cta_keyword}</span><span class="dim" style="font-size:12px">updated ${rel(c.updated_at || c.created_at)}</span></div>
          ${k ? html`<div class="row dim" style="font-size:12.5px;margin-top:8px;gap:14px"><span>${icon("message-circle")} ${Object.values(st).reduce((a, b) => a + b, 0)} comments matched</span><span>${icon("send")} ${st.RESOURCE_SENT || 0} guides sent</span><span>${icon("user-plus")} ${(st.AWAITING_FOLLOW || 0)} waiting to follow</span></div>` : ""}
        </div>
        <div class="post-act">${next}
          ${c.permalink ? html`<a class="btn sm" href="${c.permalink}" target="_blank" rel="noopener">${icon("external-link")}View</a>` : ""}
          ${k ? html`<label class="row" style="gap:8px;font-size:12.5px" title="Auto-reply to comments with ${c.cta_keyword}"><span class="switch"><input type="checkbox" data-camp="${k.id}" ${k.active ? "checked" : ""}><i></i></span>Auto-reply</label>` : ""}
        </div></div>`;
    };
    view.onchange = async (e) => {
      const t = e.target.closest("[data-camp]");
      if (!t) return;
      try { await api(`/api/campaigns/${t.dataset.camp}`, { method: "PUT", body: { active: t.checked } }); toast(`Auto-reply ${t.checked ? "on" : "off"}`, "ok"); }
      catch (err) { t.checked = !t.checked; toast(err.message, "err"); }
    };
    await load();
  },
};

import { $, $$, api, badge, busy, emptyState, html, icon, mount, num, rel, toast, ist } from "../ui.js";

const CAT_ICON = { "AI Industry News": "newspaper", "Trending GitHub": "github", "AI Developer Tools": "terminal-square", "AI Creator Tools": "wand-2",
  "Video & Animation": "clapperboard", "Open-Source Projects": "package-open", "Tutorials & Workflows": "list-checks" };
const FMT = { SINGLE: "Single image", CAROUSEL: "Carousel", REEL: "Reel (demo)" };

let off = null;

function meter(label, v, color) {
  return html`<div class="meter"><div class="row"><span>${label}</span><span class="mono">${v ?? "—"}</span></div><div class="bar"><i style="width:${v || 0}%;background:${color}"></i></div></div>`;
}

function story(t, lead, minScore) {
  const host = (() => { try { return new URL(t.url).hostname.replace("www.", ""); } catch { return t.source; } })();
  const fmt = t.suggested_format ? `${FMT[t.suggested_format] || t.suggested_format}${t.suggested_format !== "SINGLE" ? ` · ${t.suggested_slides} slides` : ""}` : "Not scored";
  return html`<article class="card story ${lead ? "lead" : ""}" data-id="${t.id}">
    <div>
      <div class="meta">${icon(CAT_ICON[t.category] || "circle")}<span>${t.category}</span><span>·</span><span>${host}</span><span>·</span><time title="Published ${t.published_date}">${t.published_date || "date unknown"}</time></div>
      <h2><a href="${t.url}" target="_blank" rel="noopener">${t.title}</a></h2>
      <p class="sum">${t.description || t.why_it_matters || "No summary available from the source."}</p>
      ${t.why_it_matters && t.description ? html`<p class="sum" style="margin-top:8px;color:var(--text)"><b style="font-weight:600">Why it matters:</b> ${t.why_it_matters}</p>` : ""}
      ${t.facts.length ? html`<div class="facts">${t.facts.slice(0, lead ? 6 : 4).map((f) => html`<span>${f}</span>`)}</div>` : ""}
      <div class="story-actions">
        ${t.drafts.length ? html`<a class="btn sm" href="#creator?id=${t.drafts[0]}">${icon("pen-tool")}Open draft #${t.drafts[0]}</a>`
          : html`<button class="btn sm primary" data-act="create" ${t.verification_status !== "VERIFIED" ? "title='Verify the source first'" : ""}>${icon("sparkles")}Create content</button>`}
        <button class="btn sm" data-act="verify">${icon("refresh-cw")}Re-verify</button>
        <a class="btn sm ghost" href="${t.url}" target="_blank" rel="noopener">${icon("external-link")}Original</a>
        ${t.status !== "DISMISSED" && !t.drafts.length ? html`<button class="btn sm ghost" data-act="dismiss">${icon("eye-off")}Dismiss</button>` : ""}
      </div>
    </div>
    <div class="side-col">
      ${t.preview_image_url ? html`<div class="thumb"><img src="${t.preview_image_url}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentNode.remove()"></div>` : ""}
      <div class="row">${badge(t.verification_status || "UNVERIFIED")}${t.opportunity_score >= minScore ? html`<span class="chip info">Recommended</span>` : ""}</div>
      ${meter("Practical usefulness", t.usefulness, "linear-gradient(90deg,#4c7dff,#3be0ff)")}
      ${meter("Audience relevance", t.relevance, "linear-gradient(90deg,#8b5cf6,#4c7dff)")}
      <div class="dim" style="font-size:12px">${icon("layout-template")} Suggested: <span style="color:var(--text-2)">${fmt}</span></div>
      <div class="dim" style="font-size:11.5px" title="${t.verification_note}">${t.verification_note || ""}</div>
    </div>
  </article>`;
}

export default {
  title: "Daily Intelligence",
  eyebrow: "Research · verified sources only",
  async render(view, app) {
    let cat = app.params.get("cat") || "", q = "", showLow = false, topics = [];
    app.setActions(html`<button class="btn primary" id="harvest">${icon("radar")}Run research now</button>`);
    mount(view, html`<div class="intel-layout">
      <nav class="cat-list" id="cats" aria-label="Categories"></nav>
      <div class="stack" style="gap:16px">
        <div class="row" style="justify-content:space-between">
          <input class="input" id="q" placeholder="Search stories…" style="max-width:320px" aria-label="Search stories">
          <label class="row dim" style="font-size:12.5px;gap:8px"><span class="switch"><input type="checkbox" id="low"><i></i></span>Show low-priority & dismissed</label>
        </div>
        <div id="jobBox"></div>
        <div class="stories" id="list"></div>
      </div></div>`);

    const draw = () => {
      const s = app.state, minScore = 65;
      const visible = topics.filter((t) => showLow || (t.status !== "DISMISSED" && t.status !== "LOW_PRIORITY"));
      const counts = {};
      visible.forEach((t) => (counts[t.category] = (counts[t.category] || 0) + 1));
      mount($("#cats"), html`<button class="${!cat ? "on" : ""}" data-cat="">${"All stories"}<span class="n">${visible.length}</span></button>
        ${s.categories.map((c) => html`<button class="${cat === c ? "on" : ""}" data-cat="${c}"><span class="row" style="gap:9px">${icon(CAT_ICON[c])}${c}</span><span class="n">${counts[c] || 0}</span></button>`)}`);
      const rows = visible.filter((t) => (!cat || t.category === cat) && (!q || (t.title + t.description).toLowerCase().includes(q)));
      rows.sort((a, b) => (b.verified_date || "").localeCompare(a.verified_date || "") || b.opportunity_score - a.opportunity_score);
      mount($("#list"), rows.length ? html`${rows.map((t, i) => story(t, i === 0 && !q, minScore))}`
        : emptyState("radar", topics.length ? "No stories match" : "No research yet", topics.length ? "Try another category or clear the search." : "Run research to pull today's AI news, GitHub repos and open models — every source gets verified.",
          !topics.length ? html`<button class="btn primary sm" onclick="document.getElementById('harvest').click()">Run research</button>` : ""));
      const j = s.running.find((x) => x.kind === "research" || x.kind === "pipeline");
      mount($("#jobBox"), j ? html`<div class="job"><div class="spread"><span class="chip live"><span class="dot"></span>Research running</span><span class="mono dim">${j.progress}%</span></div><div>${j.stage}</div><div class="progress"><i style="width:${j.progress}%"></i></div></div>` : "");
    };
    const load = async () => {
      mount($("#list"), html`${[1, 2, 3].map(() => html`<div class="skel" style="height:180px;border-radius:16px"></div>`)}`);
      topics = await api("/api/topics");
      draw();
    };
    await load();
    let wasRunning = !!app.state.running.length;
    off = app.on((s) => { const r = !!s.running.length; if (wasRunning && !r) load(); else draw(); wasRunning = r; });

    $("#cats").onclick = (e) => { const b = e.target.closest("[data-cat]"); if (b) { cat = b.dataset.cat; draw(); } };
    $("#q").oninput = (e) => { q = e.target.value.toLowerCase(); draw(); };
    $("#low").onchange = (e) => { showLow = e.target.checked; draw(); };
    $("#harvest").onclick = (e) => busy(e.currentTarget, async () => {
      try {
        const j = await app.startJob("/api/research/run", {}, "Research");
        if (j) toast(j.status === "SUCCESS" ? `Research done — ${JSON.parse(j.result_json || "{}").found ?? 0} new, verified ${JSON.parse(j.result_json || "{}").verified ?? 0}` : `Research failed: ${j.error}`, j.status === "SUCCESS" ? "ok" : "err");
        await load();
      } catch (err) { toast(err.message, "err"); }
    });
    $("#list").onclick = async (e) => {
      const b = e.target.closest("[data-act]");
      if (!b) return;
      const id = +b.closest("[data-id]").dataset.id, t = topics.find((x) => x.id === id);
      if (b.dataset.act === "create") {
        if (t.verification_status !== "VERIFIED") return toast("Verify the source before creating content.", "err");
        await busy(b, async () => {
          try {
            const c = await api("/api/carousels", { method: "POST", body: { topic_id: id } });
            toast(c.note || `Draft #${c.id} created (${c.slide_count} slides)`, "ok");
            app.go("creator", { id: c.id });
          } catch (err) { toast(err.message, "err"); }
        });
      } else if (b.dataset.act === "verify") {
        await busy(b, async () => {
          try {
            const r = await api(`/api/topics/${id}/verify`, { method: "POST" });
            toast(`${r.topic.verification_status}: ${r.topic.verification_note}`, r.topic.verification_status === "VERIFIED" ? "ok" : "err");
            await load();
          } catch (err) { toast(err.message, "err"); }
        });
      } else if (b.dataset.act === "dismiss") {
        await api(`/api/topics/${id}/dismiss`, { method: "POST" });
        t.status = "DISMISSED";
        draw();
      }
    };
  },
  destroy() { off && off(); },
};

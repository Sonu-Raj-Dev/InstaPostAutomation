# Deployment Checklist (do nothing here without your explicit approval)

Every step that touches production, Meta or QStash is marked **[approval]**. I'll do those only when you say so, one at a time.

## 0. Important: deploying = migrating
The app runs its database migration **automatically on the first request** after a deploy (existing behaviour, under a Postgres advisory lock). Merging to `main` therefore **applies the schema changes to production**. They're additive and backward compatible, but test them first (step 2).

## 1. Prepare (no production impact)
- [ ] Review the branch diff and reports.
- [ ] Commit to `feat/publishing-reliability` and open a PR (not merged). **[approval]**
- [ ] Create a free **Upstash** account → QStash → copy `QSTASH_TOKEN`, `QSTASH_CURRENT_SIGNING_KEY`, `QSTASH_NEXT_SIGNING_KEY` (and the region URL if shown). Check it's on the free plan.

## 2. Test the migration on a database branch **[approval]**
Vercel Postgres is Neon-based, so create a **branch** of the production database (Neon/Vercel Storage → Branches). It's a copy, and production is untouched.
- [ ] Run against the branch from your machine: `DATABASE_URL=<branch url> python -c "import sys; sys.path[:0]=['src']; from db.migrate_v2 import migrate; migrate(); migrate()"`
- [ ] Confirm the new tables exist (`webhook_events`, `dm_delivery_log`, `job_locks`) and existing row counts are unchanged.
- [ ] Optional: point a **Preview** deployment's `DATABASE_URL` at the branch and click through the dashboard. **Make sure Preview deployments don't use the production `DATABASE_URL`.**

## 3. Environment variables (Vercel → Project → Settings → Environment Variables, Production) **[approval / you]**
- [ ] `META_APP_SECRET`: required, otherwise all webhooks are rejected (503)
- [ ] `QSTASH_TOKEN`, `QSTASH_CURRENT_SIGNING_KEY`, `QSTASH_NEXT_SIGNING_KEY` (+ `QSTASH_URL` if regional)
- [ ] `APP_URL` = `https://insta-post-automation-pi.vercel.app` (exact; QStash callbacks are verified against it)
- [ ] `CRON_SECRET` (for the daily maintenance cron)
- [ ] `META_PAGE_ACCESS_TOKEN`: long-lived Page token for "Anime Wala" (for DMs)
- [ ] New `META_ACCESS_TOKEN` including `pages_manage_metadata` (or renew it in Settings after deploy)

## 4. Deploy **[approval]**
- [ ] Merge the PR → Vercel builds the production deployment.
- [ ] Open the app once (this triggers the migration). Check `GET /api/health` → `ok`.
- [ ] Log in → Automation: the six system cards load; Webhook health shows the secret "Configured" and QStash "Configured".

## 5. Schedules **[approval]**
- [ ] Automation → Configuration → **Save** (or Webhook health → **Sync now**). The toast should say "QStash schedules updated".
- [ ] QStash console: exactly **5** schedules `sal-research`, `sal-generate`, `sal-publish`, `sal-analytics`, `sal-tick`, with the destination `https://insta-post-automation-pi.vercel.app/api/queue/job/...` and the times you set (`CRON_TZ=Asia/Kolkata`).
- [ ] Wait for one `sal-tick` (≤10 min): a **maintenance** job appears in Jobs as SUCCESS.

## 6. Meta configuration **[you / approval]**
Follow `meta_configuration_checklist.md` §3: app mode, Advanced Access, webhook callback + verify token, subscribe `comments` + `messages`, Page token, **Page→app subscription (changes Meta config: approval)**.
- [ ] Webhook health → **Check Meta configuration** → no errors; "To do" only lists the dashboard-only items.
- [ ] Webhook health shows "Verified".

## 7. Watch first events (read-only)
- [ ] Comment-to-DM → *Incoming webhook events* shows real events within seconds of a comment on any post.
- [ ] QStash console → usage stays well under 1,000/day.

## 8. Investigate the old publish failure (optional, read-only)
- [ ] Approval → the failed post → the error now shows Meta's message, code, subcode and fbtrace.

## 9. ONE approved live publishing test **[approval required at the moment of the test]**
- [ ] You pick the post. Approval → **Approve & publish** → the stages show Validating → Uploading → Processing → Publishing → Published → "View post" opens it on Instagram.
- [ ] Check: one post on @sonu.ai.lab, not two; Webhook health and Publishing card updated.

## 10. ONE approved comment-to-DM test **[approval required at the moment of the test]**
- [ ] From a **second** account (if the app is still in Development mode, that account must have a role on the app), comment `AGENT` on the published post.
- [ ] Expected: the event appears as PROCESSED; the delivery shows "Waiting for button tap"; that account receives **one** private reply → tap the button → guide text + link + images → "Resource sent".
- [ ] Comment `agent` again from the same account → "Already served", no second message.

## Rollback (if anything is wrong)
1. **Code:** Vercel → Deployments → previous production deployment → **Promote to Production** (instant).
2. **QStash:** console → **delete or pause** the 5 `sal-*` schedules. The old code has no `/api/queue/job/*` endpoints, so they'd only fail and burn messages.
3. **Crons:** the previous deployment brings back its own `vercel.json`. Note that the version before this work had **fixed crons at 17:30 / 19:00 IST** that run the old combined pipeline. Pause the scheduler in Settings if you don't want that.
4. **Database:** no rollback needed. The changes are additive, and the old code ignores the new columns and tables (its INSERTs name their columns and new columns have defaults). Don't drop anything.
5. **Meta:** nothing to undo for webhooks. The old code accepts them as before.
6. **Env vars:** new variables are harmless to the old code and can stay.

## Monitoring (first 48 h)
Automation → Systems (failures, latest error) · Webhook health (last event, failed DMs) · QStash usage · Approval → Failed tab.

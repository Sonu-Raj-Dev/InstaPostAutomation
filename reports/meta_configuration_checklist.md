# Meta Configuration Audit + Checklist (Phase 7)

Audit run on 2026-11-21 with **read-only GET requests** (`src/meta_audit.py`) using the credentials in the local `.env`. Nothing at Meta was changed: no app mode change, no app review request, no subscription change. No token appears in this report or in stored results.

> **Scope:** production may have a newer token saved in its database (Settings → renew token) and has its own Vercel env vars. After deploying, click **Automation → Webhook health → Check Meta configuration** to run the same audit with the production credentials. That run also reads the webhook subscriptions, which need `META_APP_SECRET` (not set locally).

## 1. What the audit found (local credentials)

| Item | Result | Status |
|---|---|---|
| Meta app | "Personal-Content-CMS", id matches `META_APP_ID` | ✅ |
| **App mode** (Development / Live) | **Not exposed by the Graph API**, so not reported | ❓ check the dashboard |
| **Advanced Access** | **Not exposed by the Graph API**, so not reported | ❓ check the dashboard |
| Token type | **USER** token | ⚠️ see messaging |
| Token validity / expiry | Valid; **never expires** (long-lived). **Data access expires 2027-02-18** (Meta's 90-day data-access window; renews when you use the app or re-authorize) | ✅ (note the date) |
| Connected Facebook Page | **"Anime Wala"** (id 1197692756750053), the only Page on the token | ✅ |
| Instagram account | **@sonu.ai.lab** (id 17841432923011052, 136 followers), a professional account linked to that Page. Matches `INSTAGRAM_ACCOUNT_ID` | ✅ |
| Instagram account type | Professional (Business or Creator). The exact sub-type isn't exposed for Page-linked accounts | ✅ |
| Permissions granted | instagram_basic, instagram_content_publish, instagram_manage_comments, instagram_manage_messages, instagram_manage_insights, pages_show_list, pages_read_engagement, business_management, public_profile | ✅ |
| **Permission missing** | **pages_manage_metadata** (needed to subscribe the Page to the app for webhooks; Meta returned *"(#200) Requires pages_manage_metadata permission"*) | ❌ |
| Comment webhook subscription (app level) | **Unknown here**: needs `META_APP_SECRET` | ❓ run in production |
| Messaging webhook subscription (app level) | **Unknown here**: needs `META_APP_SECRET` | ❓ run in production |
| Page → app subscription | **Couldn't check** (missing pages_manage_metadata) | ❌ / ❓ |
| Messaging endpoint | The main token is a **USER** token. Instagram private replies and DMs go through the Page (`/{page-id}/messages` or `me/messages` **with a Page token**), so with only a User token, DM sends are expected to fail. The app now uses `META_PAGE_ACCESS_TOKEN` for messaging when it's set | ❌ until set |

Granular scopes show no target restrictions (the permissions aren't limited to specific Pages or accounts).

## 2. What this means for the features
* **Publishing:** the permissions are present. The real reason for past publish failures will now show in the dashboard (Phase 2).
* **Comment webhooks:** they can't work until **(a)** `META_APP_SECRET` is set, **(b)** the app's Instagram webhook is subscribed to `comments` (and `messages`), **(c)** the Page is subscribed to the app, which needs `pages_manage_metadata`, and **(d)** the app is **Live** with **Advanced Access** if commenters who aren't app testers should trigger it.
* **Comment-to-DM:** additionally needs a **Page access token** (`META_PAGE_ACCESS_TOKEN`).

## 3. Manual checklist (Meta App Dashboard, by you)
Nothing below has been done by me. Each step changes your Meta setup, so it's yours to do, or approve.

1. **App mode:** App Dashboard top bar shows *Development* or *Live*. In Development, **only people with a role on the app** (admins, developers, testers) generate webhooks and can receive replies. For real followers it must be **Live**.
2. **Advanced Access:** App Review → Permissions and Features. For non-role users you need **Advanced Access** for `instagram_basic`, `instagram_manage_comments`, `instagram_manage_messages`, `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`, plus `instagram_content_publish` / `instagram_manage_insights` as used. This usually requires App Review and Business Verification.
3. **App secret:** App settings → Basic → *App secret* → Vercel env **`META_APP_SECRET`**.
4. **Webhook (Instagram object):** Webhooks → Instagram → callback **`https://insta-post-automation-pi.vercel.app/api/webhooks/instagram`**, verify token from **Settings → Webhook** in the app → *Verify and save* → subscribe fields **`comments`** and **`messages`** (optional: `messaging_postbacks`). After verifying, the Webhook health panel shows "Verified".
5. **New token with `pages_manage_metadata`:** Graph API Explorer / your login flow → add `pages_manage_metadata` (keep the existing scopes) → exchange for a long-lived token → save in **Settings**.
6. **Page token for messaging:** with that long-lived *user* token, `GET /me/accounts` gives the Page's long-lived **Page access token** → Vercel env **`META_PAGE_ACCESS_TOKEN`**. (I can add an in-app "derive Page token" button if you want. It would only read `/me/accounts`.)
7. **Subscribe the Page to the app:** `POST /1197692756750053/subscribed_apps?subscribed_fields=feed` with the Page token (or the "Subscribe" button in the Webhooks product). **This changes Meta configuration.** I'll only do it on your explicit approval.
8. **Re-run** *Check Meta configuration* in production. The goal is no errors and an empty "To do" list, apart from the dashboard-only items (mode, Advanced Access).

## 4. Vercel environment variables (Meta-related)
| Variable | Status (local .env) | Needed for |
|---|---|---|
| `META_ACCESS_TOKEN` | set (USER token) | Publishing, insights |
| `INSTAGRAM_ACCOUNT_ID` | set (matches) | All IG calls |
| `META_APP_ID` | set (matches token's app) | Audit, token exchange |
| `META_APP_SECRET` | **empty** | **Webhook signatures (required)**, audit of subscriptions |
| `META_PAGE_ACCESS_TOKEN` | not set | **Private replies / DMs** |
| `META_MESSAGING_NODE` | not set (default `me`) | Only if you send with a non-Page token (not recommended) |

## 5. App changes in Phase 7
* `src/meta_audit.py` (new): the read-only audit. It distinguishes **"couldn't check"** from **"not configured"**, so a network error is never reported as an invalid token (bug found and fixed during the live run).
* `POST /api/meta/audit` (stores a token-free result) and `GET /api/meta/audit`. The Webhook health panel shows the subscription status from it, plus a **Check Meta configuration** button with a results dialog.
* `CommentResponder` uses `META_PAGE_ACCESS_TOKEN` for messaging when set (publishing unchanged).
* Tests: `tests/test_meta_audit.py` (6). They check that only GET is used, no token appears in the output, unknowns aren't assumed, mismatches are flagged, and the result reaches the health panel. Full suite **136 passed**.

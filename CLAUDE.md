# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Telegram bot (aiogram 3, polling mode) that gates a private VIP **channel** by verifying each user's Exness trading account against the operator's affiliate (IB) link via the Exness Partnership API. New users go through a funnel (email → phone → Exness ID), get an auto-approved single-use channel invite once "activated" (first trade OR deposit ≥ `MIN_DEPOSIT_USD`), and are periodically re-checked — kicked if they change partner, empty their balance, or go dormant. One bot, one channel, one operator. Client-facing docs are in `README.md`; this file is for working on the code.

## Commands

```bash
./setup.sh                 # create .venv, install requirements.txt, aerich init-db (first run) / aerich upgrade
cp .env.example .env        # then fill it in — see README ".env reference" table
.venv/bin/python main.py    # run in foreground (Ctrl+C to stop)

./bot.sh start|stop|restart|status|logs|update   # nohup+pidfile production wrapper
sudo ./deploy.sh                                  # alternative: install/refresh a systemd unit

.venv/bin/aerich migrate --name <name>   # generate a migration after a models.py change
.venv/bin/aerich upgrade                  # apply migrations
```

There is **no automated test suite**. Verification is done by ad-hoc scripts hitting the real API — e.g.:

```bash
.venv/bin/python -c "import asyncio; from exness_api import fetch_snapshot; print(asyncio.run(fetch_snapshot('250324410')))"
```

`TEST_MODE=true` in `.env` makes every `fetch_*` return a fake "activated" snapshot, so the whole Telegram flow can be exercised end-to-end without burning real referral data. Telegram-side calls (channel invites, ban/unban) still hit the real API in TEST_MODE. **Always set `TEST_MODE=false` before handing the bot to real users.**

## Architecture

**Entry point** `main.py`: sets up logging, `init_db()`, `Bot`/`Dispatcher`, includes routers, runs the Exness self-test, starts the scheduler, then `dp.start_polling(...)` with `allowed_updates` covering `message`, `callback_query`, `chat_member`, `chat_join_request`, `my_chat_member`.

**Router order matters** (`handlers/__init__.py`): `channel` → `commands` → `admin` → `relay`. `relay` is a private-chat catch-all (`StateFilter(None)`) and MUST stay last so it doesn't swallow FSM input or admin commands. `admin` is filtered by `F.from_user.id.in_(ADMIN_IDS)` + private chat.

**User flow** lives in `handlers/commands.py`. Main menu: How It Works / Register on Exness / Join VIP for Free / Check Status (exact order is a client requirement — see README). "Join VIP for Free" → "Do you have an Exness account?" → either the **funnel** (`VerifyState.awaiting_email` → `awaiting_phone` → `awaiting_uid`, orchestrated by `_enter_funnel()` which jumps to the first missing piece) or the "Switch Partner" / "Create New Exness Account" instruction screens. After the funnel, `_verify_and_route()` does one `fetch_snapshot()` and renders one of: not-connected / pending / approved. `_ensure_user()` is used at every funnel entry point — without it, a user who reached a callback without ever sending `/start` could loop the email prompt forever.

**The Exness API client** `exness_api.py` is the part with the most non-obvious behavior, all of it discovered by live probing:

- Auth: `POST /api/v2/auth/` with `{login, password}` → JWT, ~6h TTL. Cached in memory (`_TokenCache` + `asyncio.Lock`), refreshed proactively (5 min margin) and on any 401. Auth header is `Authorization: JWT <token>`.
- **`client_uid` is a UUID.** `/api/v2/reports/clients/?client_uid=<UUID>` works and returns the full row. Passing it anything that isn't a full UUID (an 8-char hex prefix, a numeric trading account number) returns **HTTP 500**. So `resolve_client_uid()` upgrades user input to a canonical UUID first:
  - full UUID → used as-is (lower-cased);
  - 8-9 digit trading account number → `/api/reports/clients/accounts/?client_account=<N>` to get the (truncated 8-char) `client_uid`, then `_clients_paginated()` to find the row whose full UUID starts with that prefix;
  - 8+ char hex prefix (what Exness emails the partner on new registrations) → straight to the `_clients_paginated()` prefix match;
  - ambiguous prefix (>1 match) or no match → `NOT_FOUND` sentinel.
  `/api/reports/clients/accounts/` **truncates `client_uid` to 8 hex chars**; `/api/v2/reports/clients/` returns the full 36-char UUID — that mismatch is why the paginated scan exists. `_persist_snapshot()` writes the canonical UUID back to `User.exness_uid` so later re-checks skip the scan.
- **Numeric fields are placeholders when there's no real activity.** Accounts that have never deposited AND never traded come back with the placeholder `1` across *all* numeric fields: `deposit_amount=1`, `client_balance=1`, `client_equity=1`, `ftd_amount=1`, no progress flags. `fetch_snapshot()` recognizes that exact pattern (all numeric ≤ 1 AND no `ftd_received`/`ftt_made` flag) and zeroes `deposit_total`/`balance`. Any value above the placeholder is real and is trusted — including before the `ftd_received` flag flips (it can lag the deposit figure by hours, which is what left a real depositor stuck on "pending — make a deposit" once).
- **No email lookup exists.** The API has no email/phone filter and no `client_email` field on client rows. The email collected in the funnel is for the operator's records only (`/user <email>`, `/export`) — verification is always by trading account number / UUID.
- `fetch_snapshot()` returns `None` on any transient error (network, 5xx, bad JSON), an "empty" snapshot (`under_partner=False`) on a definitive miss, or a full `ClientSnapshot`. `deposit_total = max(deposit_amount, ftd_amount, 0)`. Activation: `is_activated(progress_flags, deposit_total)` = `deposit_total ≥ MIN_DEPOSIT_USD` — **gated on the deposit amount, not on the `ftd_received` flag** (the flag lags; a no-deposit bonus trade still doesn't qualify because its amount stays at/below the placeholder `1`, well under the threshold). If `ACTIVATION_REQUIRE_TRADE=true`, also requires `ftt_made`. `recheck_verified_users` re-evaluates `is_activated` and kicks (`kicked_not_activated`) accounts that no longer pass. `progress_flags` is a synthetic list built from the row's bool fields (with legacy `contact_sharing_progress_status` list support); it's used for display/audit and the optional trade requirement, not the deposit gate.
- `client_status` enum: `ACTIVE` / `INACTIVE` / `LEFT` / `CHANGING`.

**Scheduler** `scheduler.py` (apscheduler, three jobs):
1. `check_pending_users` every `PENDING_POLL_MINUTES` — only for `status='pending'` rows whose `pending_since` is within `PENDING_AUTO_GIVEUP_HOURS` (older ones are left alone; a manual "Re-check now" resets `pending_since`).
2. `recheck_verified_users` every `RECHECK_INTERVAL_HOURS` — for `verified`/`warned`. Kick triggers: not under partner / `client_status in (LEFT, CHANGING)` → immediate; `not is_activated(...)` → no longer meets the deposit gate; `deposit_total ≥ MIN_DEPOSIT_USD` (had a real deposit) AND `balance < 1` → withdrew everything; inactivity past `INACTIVITY_WARN_DAYS` → warn, then kick after `WARNING_GRACE_DAYS` if still inactive (recovers if active again). **Inactivity logic is skipped entirely when there's no `last_trade_at` timestamp** — a deposit-only user must never be kicked for "no trades". The per-user logic is `recheck_one_user(bot, user)`, also reachable via the admin `/recheck` command.
3. `daily_cleanup` — prunes `AuditLog` rows older than 90 days.

**The cardinal rule (don't break it):** a transient API error is never grounds to kick. `fetch_snapshot()` returning `None` → increment `consecutive_api_errors`, log, retry next cycle. Only a definitive negative answer (`under_partner=False`, `LEFT`, empty balance) triggers a kick. Kicking a paying VIP because of a network blip is the worst failure mode.

**Channel mechanics**: invite links are minted per-user via `create_chat_invite_link(member_limit=1, expire_date=now+24h)` — single-use, 24h. Kicking is `ban_chat_member` then `unban_chat_member(only_if_banned=True)` so the user can re-join later if they re-qualify. `handlers/channel.py` auto-approves `chat_join_request` only for `verified` users and declines everyone else; `my_chat_member` is telemetry-only.

**Data** (`models.py`, tortoise-orm + SQLite at `data/db.sqlite3`): `User` (status state machine: `onboarding` → `pending` → `verified` ⇄ `warned` → `kicked`; carries email/phone/exness_uid plus snapshot fields), `RelayMessage` (maps a forwarded admin-side message back to the originating user; the DM relay broadcasts to *every* admin in `ADMIN_IDS`, any of whom can reply), `AuditLog` (append-only state-transition log; surfaced via `/audit`). `init_db()` runs `generate_schemas(safe=True)` plus a defensive `ALTER TABLE ... ADD COLUMN` for each newer column — this is the robust upgrade path (aerich migrations are committed but secondary; regenerating them when the local DB is out of sync is finicky, so prefer adding to the defensive ALTER list in `utils.py`).

## Conventions

- Chat copy / messages: short, emoji-headed, plain text (no `parse_mode` unless a message specifically needs `<code>` for tap-to-copy, in which case escape with `html.escape`). Long admin replies go through `_send_long()` in `handlers/admin.py` (chunks on `\n`, stays under Telegram's 4096-char limit).
- All DB timestamps are UTC; `utils.fmt_dt()` converts to `DISPLAY_TZ` for admin-facing output.
- Config knobs all come from `.env` via `config.py` helpers — never hard-code intervals/thresholds. `ADMIN_IDS` is comma-separated; legacy single `ADMIN_ID` still parsed.
- When changing user-facing copy, it's mostly module-level string constants in `handlers/commands.py` — the client iterates on wording frequently.

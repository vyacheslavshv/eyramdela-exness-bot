# Exness Affiliate VIP Bot

Telegram bot that gates a private VIP **channel** by checking each user's
Exness trading account against your IB code and activation criteria.
Users who change partner, withdraw all funds, or become dormant are
auto-removed.

---

## How it works

**For your users**

1. The user opens the bot and taps `/start`. The main menu has four
   buttons, in this order:
   * 📖 How It Works — the step-by-step explainer.
   * 🟢 Register on Exness — shows your partner link + a "Join VIP for
     Free" prompt.
   * 🚀 Join VIP for Free — the verification funnel (below).
   * 📊 Check Status — re-runs a check and reports Approved / Pending /
     Not connected.
2. **Join VIP for Free** first asks: *"Do you already have an Exness
   account?"* with three choices:
   * ✅ **Yes, my account is under you** → the funnel asks, in order:
     1. **Email address** used for the Exness account.
     2. **Phone number** (Telegram contact-share button, or typed).
     3. **Exness ID (Trading Account Number)** — the bot accepts the
        8-9 digit trading account number (what users see in *My
        Accounts* — **the recommended format**), a full Client UUID,
        or the 8-char hex Client ID prefix that Exness emails to you
        as a partner.
   * ❌ **My account is NOT under you** → shows the step-by-step
     "Switch Partner on Exness" instructions (log in → Live Chat →
     "Change Partner" → Signals/Education → submit via your partner
     link → wait for approval → create a NEW MT4/MT5 account →
     transfer funds → archive old). Plus a **🆕 Create New Exness
     Account** button for the case where Exness rejects the partner
     change ("user not eligible"), which shows the create-a-fresh-
     account flow (your partner link + tap-to-copy partner code).
   * 📊 Check My Status.
3. After the funnel, the bot calls the Exness Partnership API:
   * **Not connected under your partner** → "❌ Your account is
     currently not connected under our partner link" + buttons:
     🔀 Switch Partner, ✏️ I entered the wrong ID, 📊 Check My Status.
   * **Connected but not activated** → "🟡 Almost there!" — the client
     must have made a first deposit, in a deposit *tier* at or above
     `MIN_DEPOSIT_USD`. (A no-deposit bonus trade does *not* count.)
     Exness reports deposits as a tier, not an exact dollar figure —
     `1: $0–10 · 2: $10–50 · 3: $50–250 · 4: $250–1000 · 5: $1000–5000
     · 6: >$5000` — so `MIN_DEPOSIT_USD=50` means "tier 3 or higher",
     and `MIN_DEPOSIT_USD=0` means "any deposit at all". If
     `ACTIVATION_REQUIRE_TRADE=true`, a trade is also required. Direct
     deep links to **💵 Make a Deposit** and **📈 Open Exness (Trade)**.
     The bot auto-checks every `PENDING_POLL_MINUTES` for the next
     `PENDING_AUTO_GIVEUP_HOURS` hours; after that, the user taps
     **🔁 Re-check now** to resume.
   * **Activated** → "🎉 Congratulations! ✅ VIP Access Approved" + a
     single-use channel invite link that expires in 24 hours. The bot
     auto-approves the join request. A **🔗 Get Invite Link Again**
     button mints a fresh link on demand.

> **Note on email.** The Exness Partnership API has no email-based
> lookup — verification is always done by the trading account number.
> The email is collected for your records (it shows up in `/user` and
> `/export`, and you can look a user up by it with `/user <email>`).
> Partner-change detection works regardless, via the re-check loop.

**For verified users (re-check loop)**

Every `RECHECK_INTERVAL_HOURS`, the bot re-verifies every active member:

* **Partner change** / `LEFT` / `CHANGING` / no longer in your client
  list → kicked immediately with a DM explaining why.
* **No qualifying deposit** — account is still under the partner but
  no longer meets the deposit gate (no first deposit, or below the
  `MIN_DEPOSIT_USD` tier) → kicked. A genuine depositor's tier doesn't
  drop below the bar, so this only ever catches accounts that got in
  without a real deposit (e.g. a no-deposit bonus trade).
* **Inactivity** past `INACTIVITY_WARN_DAYS` (no trades) → warned via
  DM. If still inactive after `WARNING_GRACE_DAYS`, kicked. If they
  trade again before the kick, automatically restored. (Users who
  qualified by deposit alone, with no trade timestamp, are never
  kicked for inactivity.)
* **Transient Exness API errors NEVER kick.** Only a definitive negative
  answer triggers any action.

> There's no separate "withdrew all funds" removal: Exness reports
> balances as a coarse tier (the same `$0–10 / $10–50 / …` ranges), not
> an exact figure, so "$0" can't be told apart from "$8". The
> inactivity rule ("no trades for N days" / partner-side `INACTIVE`)
> covers the practical "this client stopped being active" case.

---

## Setup (one-time, on the VPS)

```bash
# 1. cd into the bot directory after extracting / pulling the source
cd /path/to/eyramdela-exness-bot

# 2. Set up venv + install deps + initialize DB (one-shot)
./setup.sh

# 3. Copy the env template and fill in your values
cp .env.example .env
nano .env

# 4. Sanity-run once (Ctrl+C to stop)
.venv/bin/python main.py
```

Once you've confirmed it logs `Bot started` and your `/start` works,
pick **one** of the two production modes:

```bash
# Option A — nohup + pidfile wrapper (simple, no root)
./bot.sh start
./bot.sh logs        # tail logs
./bot.sh status
./bot.sh restart
./bot.sh stop
./bot.sh update      # git pull + pip install + aerich upgrade + restart

# Option B — systemd service (Linux, requires root)
sudo ./deploy.sh
```

---

## .env reference

| Variable | What to put |
|---|---|
| `BOT_TOKEN` | From @BotFather |
| `ADMIN_IDS` | Comma-separated Telegram IDs of all admins (e.g. `12345,67890`). Get yours from @userinfobot. Single-admin setups can still use the legacy `ADMIN_ID=12345` — both names work. |
| `CHANNEL_ID` | Channel numeric ID (starts with `-100…`). Forward a channel post to @userinfobot |
| `CHANNEL_INVITE_LINK` | Optional fallback link (the bot generates fresh single-use links per user) |
| `EXNESS_BASE_URL` | `https://my.exnessaffiliates.com` |
| `EXNESS_LOGIN` | Your Exness partner-area email |
| `EXNESS_PASSWORD` | Your Exness partner-area password |
| `EXNESS_REFERRAL_LINK` | Your sign-up referral URL. Use the **direct sign-up form** — `https://one.exnessonelink.com/boarding/sign-up/a/<your_code>`. The bare `/a/<code>` link sometimes lands on a generic page instead of the registration form. |
| `EXNESS_PARTNER_CODE` | Your partner code (e.g. `gxzo6189vp`). Shown to users who already have an Exness account so they can ask Exness Live Chat to switch their partner code to yours. |
| `EXNESS_DEPOSIT_URL` | Deep link to the Exness deposit page. Default `https://my.exness.com/pa/payments-and-wallet/deposit`. Override only if Exness changes the URL. |
| `EXNESS_PA_URL` | Deep link to the Exness Personal Area (used as the "Open Exness (Trade)" button on the pending screen). Default `https://my.exness.com/pa/`. |
| `MIN_DEPOSIT_USD` | Deposit threshold to activate (default `50`). Exness reports deposits as a **tier** (`1: $0–10 · 2: $10–50 · 3: $50–250 · 4: $250–1000 · 5: $1000–5000 · 6: >$5000`), not an exact amount — so `50` ⇒ tier 3+, `10` ⇒ tier 2+, `0` ⇒ tier 1+ ("any deposit"). The client must also have a real first deposit on record (a no-deposit bonus trade doesn't count). Set to `0` if any deposit is enough. |
| `ACTIVATION_REQUIRE_TRADE` | `true` = also require the user to have placed a first trade (on top of the deposit). Default `false`. |
| `INACTIVITY_WARN_DAYS` | DM a warning after this many days idle (default `11`) |
| `INACTIVITY_KICK_DAYS` | Kick threshold for hard inactivity (default `14`) |
| `WARNING_GRACE_DAYS` | After warning, wait this many days before kick (default `3`) |
| `RECHECK_INTERVAL_HOURS` | How often to re-check each verified user (default `6`) |
| `PENDING_POLL_MINUTES` | How often to re-check pending users (default `5`) |
| `PENDING_AUTO_GIVEUP_HOURS` | After this many hours in pending without activation, the bot stops auto-checking. The user can resume by tapping **Re-check now** or sending `/start` again — that resets the window. Default `24`. |
| `BRAND_NAME` | Your community name. Appears in the welcome message and in the "How to Switch to {BRAND_NAME} on Exness" instructions. Default `VIP Signals` — **set this to your real name.** |
| `DISPLAY_TZ` | IANA tz for admin output (default `UTC`). Internal storage is always UTC |
| `TEST_MODE` | `true` bypasses Exness API for local dev — every UID is accepted as activated. Useful for end-to-end Telegram testing without real referrals. **Always set back to `false` before handing the bot over to real users.** |
| `DATABASE_URL` | `sqlite://data/db.sqlite3` (default) |

---

## Channel setup

1. Create a private Telegram **channel** (not a group).
2. Add the bot as **admin** with these rights enabled:
   * **Add Subscribers / Invite Users via Link** — lets the bot mint
     the per-user single-use invite links.
   * **Ban Users** — used to remove members who lose eligibility
     (the bot bans then immediately un-bans, so they can re-join later
     if they re-qualify).
   * **Post Messages** — only needed if you use `/broadcast_channel`.
3. Set the channel's join mode so that joining via invite link
   requires approval ("Approval to join" / "Request admin approval").
   The bot intercepts join requests and approves only verified users;
   everyone else is declined.
4. Put the channel's numeric ID (starts with `-100…`) into `CHANNEL_ID`
   in `.env`. Easiest way to get it: forward any channel post to
   @userinfobot.

---

## Admin commands

Send these in a DM to the bot from any account listed in `ADMIN_IDS`.

| Command | What it does |
|---|---|
| `/start` | Show the admin panel |
| `/help` | Full command reference |
| `/stats` | Counts per status + audit events today + live channel member count |
| `/user <telegram_id>` *or* `/user <email>` *or* `/user <UID>` | Full info dump for one user |
| `/check <UID>` | Manual Exness API check, raw JSON output for debugging |
| `/recheck <telegram_id\|email\|UID>` | Force a re-verification of one user right now — same logic the scheduler runs every `RECHECK_INTERVAL_HOURS`, including the kick path. Use this to test that auto-removal works. |
| `/kick <telegram_id>` | Manually kick + log |
| `/unflag <telegram_id>` | Restore a kicked/warned user back to verified |
| `/users [status] [page]` | Paginated list by status (`onboarding`, `pending`, `verified`, `warned`, `kicked`) |
| `/broadcast <text>` | DM all verified users (rate-limited) |
| `/broadcast_channel <text>` | Post a message to the VIP channel as the bot |
| `/export` | CSV dump of all users |
| `/audit [N]` | Last `N` audit log entries (default 30) |
| `/reload_token` | Force a fresh JWT against Exness |

**DM relay.** Any DM to the bot from a non-admin is forwarded to **every**
admin listed in `ADMIN_IDS`. Reply to the forwarded message in your chat
with the bot to answer that user — any admin can reply.

---

## Renewal & support

Hosting is included for **3 months** from delivery. Renewal is handled
via the $30/year Fiverr gig — order it once a year and we'll keep the
VPS humming.

For urgent issues during the included window, reply to the original
Fiverr order so the chat history stays in one place.

---

## Project layout

```
.
├── main.py                  # entry point
├── config.py                # .env loader
├── exness_api.py            # JWT auth + reports endpoints + UID resolver
├── models.py                # User / RelayMessage / AuditLog (tortoise-orm)
├── scheduler.py             # pending poll / recheck / daily cleanup
├── handlers/
│   ├── commands.py          # /start, the Join-VIP funnel (email → phone → UID), main-menu callbacks
│   ├── admin.py             # admin-only commands
│   ├── channel.py           # chat_join_request, my_chat_member
│   └── relay.py             # DM relay
├── utils.py                 # logging, DB init, time fmt, phone normalize
├── bot.sh                   # nohup+pidfile ops wrapper
├── setup.sh                 # venv + deps + aerich init-db
├── deploy.sh                # systemd installer / updater
├── requirements.txt
├── pyproject.toml           # aerich config
├── .env.example
├── migrations/              # aerich migrations (committed; do NOT delete)
├── data/                    # SQLite DB (gitignored)
└── logs/                    # bot.log (gitignored)
```

---

## Troubleshooting

**Bot logs say `Exness self-test FAILED`.**
Check `EXNESS_LOGIN` / `EXNESS_PASSWORD` in `.env` and run `/reload_token`
in admin DM. The bot keeps running and will retry on demand — no users
are kicked while the API is unreachable.

**A new user sees "Not under partner" but you expected them to be under it.**
Open Exness Partner Personal Area and confirm they actually appear in
your client list. New registrations can take a few minutes to surface
in the API. If it persists, run `/check <UID>` in admin DM to see the
raw response.

**Users get declined when joining the channel.**
Verify (a) the bot is a channel admin with the permissions listed above,
(b) the user is `verified` in the DB (`/user <telegram_id>` to check),
(c) the channel uses **Approval required** join mode.

**Invite link doesn't work / expired.**
Links are single-use and expire in 24h. The user can tap
**🔗 Get Invite Link Again** (shown on the success screen, on
`/start`, and under `📊 Check Status` while they're verified) to mint a
fresh one.

**A user complains they were kicked but their account is fine.**
Check `/audit <telegram_id>` for the reason. Transient API errors do
NOT kick — only definitive negative answers do. If it was a partner-
change false positive, run `/unflag <telegram_id>` and `/check <UID>`
to investigate.

**A user is stuck in `pending` forever.**
After `PENDING_AUTO_GIVEUP_HOURS` (default 24h), the bot stops auto-
checking. Ask them to tap **🔁 Re-check now** in the bot or send
`/start` — the timer resets and polling resumes.

**A user mistyped their Exness ID.**
On the "not connected" and "pending" screens there's an
**✏️ I entered the wrong ID** button — it re-prompts for the Exness ID
and re-checks immediately. (It keeps their email and phone on file.)

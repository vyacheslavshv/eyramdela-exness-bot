# Exness Affiliate VIP Bot

Telegram bot that gates a private VIP **channel** by checking each user's
Exness trading account against your IB code and activation criteria.
Users who change partner, withdraw all funds, or become dormant are
auto-removed.

---

## How it works

**For your users**

1. The user opens the bot and taps `/start`. They see a main menu:
   * 🚀 Get Free VIP Access
   * ℹ️ How It Works
   * 📊 Check My Status
   * ✏️ Change Exness ID *(only if they've already entered one)*
   * 🟢 Register on Exness *(your referral link)*
2. **Get Free VIP Access** asks for a phone number (Telegram contact
   share button) and then for the **Exness account ID**. The bot
   accepts three formats:
   * 8-9 digit trading account number (e.g. `12345678`) — the number
     the user sees on each account card in *My Accounts*. **This is
     the recommended format** since it's what users actually see.
   * Full Client UUID (e.g. `bcd562bb-1bed-49d4-…`) — internal
     identifier, rarely visible to users.
   * 8-char hex Client ID prefix (e.g. `bcd562bb`) — only what Exness
     emails to **you** as a partner on new registrations.
3. The bot calls the Exness Partnership API:
   * **Not under your partner** → user is told what to do: register
     via the green button, OR if they already have an Exness account,
     the bot prints your partner code as tap-to-copy text and tells
     them to ask Exness Live Chat to switch their partner code (Exness
     does not allow self-service partner-code change).
   * **Under your partner but not yet activated** → user lands on the
     "🟡 Almost there!" screen. The bot tells them to either deposit
     ≥ `$MIN_DEPOSIT_USD` or place their first trade, with direct deep
     links to **💵 Make a Deposit** and **📈 Open Exness (Trade)**. The
     bot then auto-checks every `PENDING_POLL_MINUTES` for the next
     `PENDING_AUTO_GIVEUP_HOURS` hours. After that window, the user can
     resume manually by tapping **🔁 Re-check now**.
   * **Activated** → the bot DMs a single-use channel invite link that
     expires in 24 hours and auto-approves the join request when the
     user clicks it.

**For verified users (re-check loop)**

Every `RECHECK_INTERVAL_HOURS`, the bot re-verifies every active member:

* **Partner change** / `LEFT` / `CHANGING` → kicked immediately with a
  DM explaining why.
* **Inactivity** past `INACTIVITY_WARN_DAYS` (no trades) → warned via
  DM. If still inactive after `WARNING_GRACE_DAYS`, kicked. If they
  trade again before the kick, automatically restored.
* **Withdrew all funds** (had a real deposit, balance now < $1) → kicked.
* **Transient Exness API errors NEVER kick.** Only a definitive negative
  answer triggers any action.

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
| `MIN_DEPOSIT_USD` | Activation threshold (default `50`) |
| `INACTIVITY_WARN_DAYS` | DM a warning after this many days idle (default `11`) |
| `INACTIVITY_KICK_DAYS` | Kick threshold for hard inactivity (default `14`) |
| `WARNING_GRACE_DAYS` | After warning, wait this many days before kick (default `3`) |
| `RECHECK_INTERVAL_HOURS` | How often to re-check each verified user (default `6`) |
| `PENDING_POLL_MINUTES` | How often to re-check pending users (default `5`) |
| `PENDING_AUTO_GIVEUP_HOURS` | After this many hours in pending without activation, the bot stops auto-checking. The user can resume by tapping **Re-check now** or sending `/start` again — that resets the window. Default `24`. |
| `BRAND_NAME` | Shown in welcome message (default `VIP Signals`) |
| `DISPLAY_TZ` | IANA tz for admin output (default `UTC`). Internal storage is always UTC |
| `TEST_MODE` | `true` bypasses Exness API for local dev — every UID is accepted as activated. Useful for end-to-end Telegram testing without real referrals. **Always set back to `false` before handing the bot over to real users.** |
| `DATABASE_URL` | `sqlite://data/db.sqlite3` (default) |

---

## Channel setup

1. Create a private Telegram **channel** (not a group).
2. Add the bot as **admin** with these permissions:
   * **Add subscribers** *(needed to generate one-time invite links)*
   * **Ban users**
   * **Post messages** *(only needed for `/broadcast_channel`)*
3. Set the channel join mode to **"Approval required"**. The bot
   intercepts join requests and approves only verified users.
4. Put the channel's numeric ID into `CHANNEL_ID` in `.env`.

---

## Admin commands

Send these in a DM to the bot from any account listed in `ADMIN_IDS`.

| Command | What it does |
|---|---|
| `/start` | Show the admin panel |
| `/help` | Full command reference |
| `/stats` | Counts per status + audit events today + live channel member count |
| `/user <telegram_id>` *or* `/user <UID>` | Full info dump for one user |
| `/check <UID>` | Manual Exness API check, raw JSON output for debugging |
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
│   ├── commands.py          # /start, FSM (phone → UID), main-menu callbacks
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
Links are single-use and expire in 24h. Ask the user to send `/start`
again; if their status is still `verified`, the bot generates a fresh
link.

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
They can fix it themselves: in the bot's main menu, tap
**✏️ Change Exness ID**. They'll be re-prompted for the correct one
and the bot will re-check immediately.

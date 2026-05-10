# Exness Affiliate VIP Bot

Telegram bot that gates a private VIP **channel** by checking each user's
Exness trading account against your IB code and activation criteria.
Users who change partner, withdraw all funds, or become dormant are
auto-removed.

## How it works

1. User opens the bot → taps **Get Free VIP Access**.
2. Bot collects phone number and the user's **Exness account ID**.
3. Bot calls the Exness Partnership API:
   * if the account is not under your partner code → user is told to
     register through your referral link.
   * if it's under your code but not yet activated → user is told to
     place their first trade or deposit ≥ `$MIN_DEPOSIT_USD`. The bot
     re-checks every few minutes.
   * once activated → bot DMs a single-use channel invite link.
4. Bot re-checks every verified user periodically:
   * partner change / `LEFT` / `CHANGING` → kick immediately.
   * inactivity past warn threshold → DM warning, kick after grace.
   * balance ≈ 0 with prior deposits → kick.
5. Admin can `/broadcast`, `/kick`, `/unflag`, `/export`, etc.

## Setup

```bash
# 1. Clone & enter
cd ~/Desktop/Fiverr/eyramdela-exness-bot

# 2. Set up venv + install deps + init DB (one-shot)
./setup.sh

# 3. Copy the env template and fill in your values
cp .env.example .env
nano .env

# 4. Try running once (Ctrl+C to stop)
.venv/bin/python main.py

# 5a. Daemonize via nohup+pidfile
./bot.sh start
./bot.sh logs        # tail logs
./bot.sh status
./bot.sh restart
./bot.sh stop
./bot.sh update      # git pull + pip install + aerich upgrade + restart

# 5b. OR install as a systemd service (Linux only, requires root)
sudo ./deploy.sh
```

## .env reference

| Variable | What to put |
|---|---|
| `BOT_TOKEN` | From @BotFather |
| `ADMIN_IDS` | Comma-separated Telegram IDs of all admins (e.g. `12345,67890`). Get yours from @userinfobot. Single-admin setups can still use the legacy `ADMIN_ID=12345` — both names work. |
| `CHANNEL_ID` | Channel numeric ID (starts with `-100…`). Forward a channel post to @userinfobot |
| `CHANNEL_INVITE_LINK` | Optional fallback link |
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
| `BRAND_NAME` | Shown in welcome message |
| `DISPLAY_TZ` | IANA tz for admin output (default `UTC`). Storage is always UTC |
| `TEST_MODE` | `true` bypasses Exness API for local dev |
| `DATABASE_URL` | `sqlite://data/db.sqlite3` (default) |

## Channel setup

1. Create a private Telegram **channel** (not a group).
2. Add the bot as **admin** with permissions:
   * Add subscribers / generate invite links
   * Ban users
   * Post messages (only needed for `/broadcast_channel`)
3. Set the channel join mode to "approval required".
4. Put the channel's numeric ID into `CHANNEL_ID` in `.env`.

## Admin commands

Send these in a DM to the bot from the admin account.

| Command | What it does |
|---|---|
| `/start` | Show the admin panel |
| `/help` | Full command reference |
| `/stats` | Counts per status + audit events today |
| `/user <telegram_id>` *or* `/user <UID>` | Full info dump for one user |
| `/check <UID>` | Manual Exness API check, raw JSON output |
| `/kick <telegram_id>` | Manually kick + log |
| `/unflag <telegram_id>` | Restore a kicked/warned user |
| `/users [status] [page]` | Paginated list by status |
| `/broadcast <text>` | DM all verified users |
| `/broadcast_channel <text>` | Post a message to the VIP channel |
| `/export` | CSV dump of all users |
| `/audit [N]` | Last `N` audit log entries |
| `/reload_token` | Force a fresh JWT against Exness |

DM relay: any DM to the bot from a non-admin is forwarded to **every**
admin listed in `ADMIN_IDS`. Reply to the forwarded message in your chat
with the bot to answer that user — any admin can reply.

## Renewal & support

Hosting is included for **3 months** from delivery. Renewal is handled via
the $30/year Fiverr gig — order it once a year and we'll keep the VPS
humming.

For urgent issues during the included window, reply to the original
Fiverr order so the chat history stays in one place.

## Project layout

```
.
├── main.py            # entry point
├── config.py          # .env loader
├── exness_api.py      # JWT auth + reports endpoints
├── models.py          # User / RelayMessage / AuditLog (tortoise-orm)
├── scheduler.py       # pending poll / recheck / cleanup
├── handlers/
│   ├── commands.py    # /start, FSM (phone -> UID), callbacks
│   ├── admin.py       # admin-only commands
│   ├── channel.py     # chat_join_request, my_chat_member
│   └── relay.py       # DM relay
├── utils.py           # logging, DB init, time fmt, phone normalize
├── bot.sh             # nohup+pidfile ops wrapper
├── setup.sh           # venv + deps + aerich init-db
├── deploy.sh          # systemd installer / updater
├── requirements.txt
└── .env.example
```

## Troubleshooting

**Bot logs say "Exness self-test FAILED".**
Check `EXNESS_LOGIN` / `EXNESS_PASSWORD` in `.env` and run `/reload_token`
in admin DM. The bot keeps running and will retry on demand.

**Users get declined when joining the channel.**
Make sure (a) the bot is a channel admin, (b) the user is `verified` in
the DB (`/user <telegram_id>` to check), (c) the channel uses
"approval required" join mode.

**A user complains they were kicked but their account is fine.**
Check `/audit` for the reason. Transient API errors do not kick — only
definitive negative answers do. If it was a partner-change false
positive, `/unflag <telegram_id>` and `/check <UID>` to investigate.

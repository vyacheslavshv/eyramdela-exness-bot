"""Admin-only commands. All filtered by ADMIN_IDS + private chat."""

from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from loguru import logger

from config import ADMIN_IDS, CHANNEL_ID
from exness_api import fetch_accounts, fetch_client, force_reauth, summarize_accounts
from models import AuditLog, User
from utils import fmt_dt, utcnow

router = Router()
router.message.filter(F.chat.type == "private", F.from_user.id.in_(ADMIN_IDS))

USERS_PAGE_SIZE = 30
BROADCAST_DELAY = 0.04   # ~25 msg/sec, under the 30 msg/sec global limit


HELP_TEXT = (
    "🛠 Admin commands\n\n"
    "/stats — counts per status, today's activity\n"
    "/user <telegram_id|UID> — full info dump for one user\n"
    "/check <UID> — manual API check, dump raw response\n"
    "/kick <telegram_id> — manual kick + DB update + audit\n"
    "/unflag <telegram_id> — restore kicked/warned user\n"
    "/users [status] [page] — list users by status\n"
    "/broadcast <text> — DM all verified users\n"
    "/broadcast_channel <text> — post to the VIP channel as the bot\n"
    "/export — CSV dump of users\n"
    "/audit [N] — last N audit log entries (default 30)\n"
    "/reload_token — force Exness JWT re-auth\n"
    "/help — this list"
)


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------
@router.message(Command("stats"))
async def cmd_stats(message: Message, bot: Bot) -> None:
    total = await User.all().count()
    by_status = {}
    for s in ("onboarding", "pending", "verified", "warned", "kicked"):
        by_status[s] = await User.filter(status=s).count()

    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    audit_today = await AuditLog.filter(created_at__gte=today_start).count()
    api_errors = (
        await User.filter(consecutive_api_errors__gt=0).count()
    )

    members_str = "—"
    if CHANNEL_ID:
        try:
            members_str = str(await bot.get_chat_member_count(CHANNEL_ID))
        except Exception:
            pass

    await message.answer(
        "📊 Stats\n\n"
        f"Total DB users: {total}\n"
        f"Channel members (live): {members_str}\n\n"
        f"Onboarding: {by_status['onboarding']}\n"
        f"Pending: {by_status['pending']}\n"
        f"Verified: {by_status['verified']}\n"
        f"Warned: {by_status['warned']}\n"
        f"Kicked: {by_status['kicked']}\n\n"
        f"Audit events today: {audit_today}\n"
        f"Users with API error streaks: {api_errors}"
    )


# ---------------------------------------------------------------------------
# /user
# ---------------------------------------------------------------------------
async def _resolve_user(query: str) -> Optional[User]:
    q = query.strip()
    if not q:
        return None
    if q.isdigit():
        u = await User.filter(telegram_id=int(q)).first()
        if u:
            return u
    return await User.filter(exness_uid=q).first()


@router.message(Command("user"))
async def cmd_user(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /user <telegram_id|exness_uid>")
        return

    user = await _resolve_user(args[1])
    if not user:
        await message.answer("User not found.")
        return

    flags = "[]"
    try:
        flags = json.dumps(json.loads(user.last_progress_flags or "[]"))
    except Exception:
        pass

    await message.answer(
        f"👤 @{user.username or '—'} ({user.first_name or '—'})\n"
        f"Telegram ID: {user.telegram_id}\n"
        f"Phone: {user.phone or '—'}\n"
        f"Exness UID: {user.exness_uid or '—'}\n\n"
        f"Status: {user.status}\n"
        f"Started: {fmt_dt(user.started_at)}\n"
        f"Verified: {fmt_dt(user.verified_at)}\n"
        f"Last check: {fmt_dt(user.last_check_at)}\n"
        f"Last warning: {fmt_dt(user.last_warning_at)}\n"
        f"Kicked: {fmt_dt(user.kicked_at)}\n\n"
        f"Last partner status: {user.last_client_status or '—'}\n"
        f"Progress flags: {flags}\n"
        f"Deposit total: ${float(user.last_deposit_total or 0):.2f}\n"
        f"Last trade: {fmt_dt(user.last_trade_at)}\n"
        f"Consecutive API errors: {user.consecutive_api_errors}"
    )


# ---------------------------------------------------------------------------
# /check
# ---------------------------------------------------------------------------
@router.message(Command("check"))
async def cmd_check(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /check <exness_uid>")
        return

    uid = args[1].strip()
    await message.answer(f"🔎 Querying Exness for UID {uid}…")

    client = await fetch_client(uid)
    accounts = await fetch_accounts(uid)

    summary = None
    if isinstance(accounts, list):
        summary = summarize_accounts(accounts)

    parts = [f"Client lookup: {uid}"]
    if client is None:
        parts.append("client endpoint: ⚠️ API error / no answer")
    elif client == {}:
        parts.append("client endpoint: ❌ data=[] (NOT under partner)")
    else:
        parts.append(
            "client endpoint: ✅\n"
            f"```\n{json.dumps(client, indent=2, default=str)[:1500]}\n```"
        )

    if accounts is None:
        parts.append("accounts endpoint: ⚠️ API error / no answer")
    else:
        parts.append(
            f"accounts endpoint: {len(accounts)} record(s)\n"
            f"```\n{json.dumps(accounts, indent=2, default=str)[:1500]}\n```"
        )
        if summary:
            parts.append(
                f"summary → deposit_total={summary['deposit_total']:.2f}, "
                f"balance={summary['balance']:.2f}, "
                f"last_trade_at={summary['last_trade_at']}"
            )

    out = "\n\n".join(parts)
    # Telegram cap is 4096; chunk if needed.
    for i in range(0, len(out), 3500):
        await message.answer(out[i:i + 3500])


# ---------------------------------------------------------------------------
# /kick
# ---------------------------------------------------------------------------
@router.message(Command("kick"))
async def cmd_kick(message: Message, bot: Bot) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /kick <telegram_id>")
        return
    try:
        tid = int(args[1].strip())
    except ValueError:
        await message.answer("Invalid telegram_id.")
        return

    user = await User.filter(telegram_id=tid).first()
    if CHANNEL_ID:
        try:
            await bot.ban_chat_member(CHANNEL_ID, tid)
            await asyncio.sleep(0.3)
            await bot.unban_chat_member(CHANNEL_ID, tid, only_if_banned=True)
        except Exception as e:
            await message.answer(f"Channel ban/unban failed: {e}")

    if user:
        await User.filter(id=user.id).update(
            status="kicked", kicked_at=utcnow()
        )
        await AuditLog.create(
            telegram_id=tid, event="kicked_by_admin", detail="manual /kick"
        )

    try:
        await bot.send_message(
            tid,
            "❌ You've been removed from the VIP channel by the admin.\n\n"
            "If you think this is a mistake, please reply here.",
        )
    except Exception:
        pass

    await message.answer(f"Kicked {tid}.")


# ---------------------------------------------------------------------------
# /unflag — restore a kicked/warned user (status=verified, no kick row)
# ---------------------------------------------------------------------------
@router.message(Command("unflag"))
async def cmd_unflag(message: Message, bot: Bot) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /unflag <telegram_id>")
        return
    try:
        tid = int(args[1].strip())
    except ValueError:
        await message.answer("Invalid telegram_id.")
        return

    user = await User.filter(telegram_id=tid).first()
    if not user:
        await message.answer("User not found.")
        return

    await User.filter(id=user.id).update(
        status="verified",
        kicked_at=None,
        last_warning_at=None,
        verified_at=user.verified_at or utcnow(),
    )
    if CHANNEL_ID:
        try:
            await bot.unban_chat_member(CHANNEL_ID, tid, only_if_banned=True)
        except Exception:
            pass

    await AuditLog.create(
        telegram_id=tid, event="unflagged_by_admin", detail="manual /unflag"
    )
    await message.answer(f"Unflagged {tid}. Status set to verified.")


# ---------------------------------------------------------------------------
# /users — list by status with pagination
# ---------------------------------------------------------------------------
@router.message(Command("users"))
async def cmd_users(message: Message) -> None:
    args = message.text.split()
    status = "verified"
    page = 1
    if len(args) >= 2:
        if args[1].isdigit():
            page = max(1, int(args[1]))
        else:
            status = args[1].lower()
    if len(args) >= 3 and args[2].isdigit():
        page = max(1, int(args[2]))

    if status not in ("onboarding", "pending", "verified", "warned", "kicked"):
        await message.answer(
            "Usage: /users [onboarding|pending|verified|warned|kicked] [page]"
        )
        return

    total = await User.filter(status=status).count()
    if total == 0:
        await message.answer(f"No users with status={status}.")
        return

    total_pages = max(1, (total + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE)
    page = min(page, total_pages)
    offset = (page - 1) * USERS_PAGE_SIZE

    rows = await User.filter(status=status).order_by("-started_at").offset(offset).limit(USERS_PAGE_SIZE)
    lines = []
    for u in rows:
        lines.append(
            f"• @{u.username or '—'} | id={u.telegram_id} | "
            f"uid={u.exness_uid or '—'} | started={fmt_dt(u.started_at)}"
        )

    header = f"{status.capitalize()} ({total}) — page {page}/{total_pages}\n\n"
    await message.answer(header + "\n".join(lines))


# ---------------------------------------------------------------------------
# /broadcast — DM all verified users
# ---------------------------------------------------------------------------
@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, bot: Bot) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Usage: /broadcast <text>")
        return
    text = args[1]

    targets = await User.filter(status="verified").all()
    if not targets:
        await message.answer("No verified users to message.")
        return

    sent = 0
    failed = 0
    progress = await message.answer(f"Broadcasting to {len(targets)} user(s)…")

    for u in targets:
        try:
            await bot.send_message(u.telegram_id, text)
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning(f"broadcast to {u.telegram_id} failed: {e}")
        await asyncio.sleep(BROADCAST_DELAY)

    try:
        await progress.edit_text(
            f"Broadcast finished.\n\nSent: {sent}\nFailed: {failed}"
        )
    except Exception:
        await message.answer(f"Broadcast finished. Sent: {sent}, Failed: {failed}")


# ---------------------------------------------------------------------------
# /broadcast_channel — post to the VIP channel as the bot
# ---------------------------------------------------------------------------
@router.message(Command("broadcast_channel"))
async def cmd_broadcast_channel(message: Message, bot: Bot) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Usage: /broadcast_channel <text>")
        return
    if not CHANNEL_ID:
        await message.answer("CHANNEL_ID is not configured.")
        return
    try:
        await bot.send_message(CHANNEL_ID, args[1])
        await message.answer("Posted to the VIP channel.")
    except Exception as e:
        await message.answer(f"Failed to post: {e}")


# ---------------------------------------------------------------------------
# /export — CSV dump
# ---------------------------------------------------------------------------
@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    rows = await User.all().order_by("started_at")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "telegram_id", "username", "first_name", "phone", "exness_uid",
        "status", "started_at", "verified_at", "last_check_at",
        "last_client_status", "last_deposit_total", "last_trade_at",
    ])
    for u in rows:
        writer.writerow([
            u.telegram_id, u.username or "", u.first_name or "",
            u.phone or "", u.exness_uid or "", u.status,
            (u.started_at.isoformat() if u.started_at else ""),
            (u.verified_at.isoformat() if u.verified_at else ""),
            (u.last_check_at.isoformat() if u.last_check_at else ""),
            u.last_client_status or "",
            (str(u.last_deposit_total) if u.last_deposit_total else ""),
            (u.last_trade_at.isoformat() if u.last_trade_at else ""),
        ])

    data = buf.getvalue().encode("utf-8")
    file = BufferedInputFile(data, filename=f"users-{utcnow():%Y%m%d-%H%M}.csv")
    await message.answer_document(file, caption=f"Total rows: {len(rows)}")


# ---------------------------------------------------------------------------
# /audit
# ---------------------------------------------------------------------------
@router.message(Command("audit"))
async def cmd_audit(message: Message) -> None:
    args = message.text.split()
    n = 30
    if len(args) >= 2 and args[1].isdigit():
        n = max(1, min(200, int(args[1])))
    rows = await AuditLog.all().order_by("-created_at").limit(n)
    if not rows:
        await message.answer("No audit log entries yet.")
        return
    lines = [
        f"{fmt_dt(r.created_at)} | tg={r.telegram_id} | {r.event}"
        + (f" | {r.detail}" if r.detail else "")
        for r in rows
    ]
    text = "🧾 Audit log (most recent first)\n\n" + "\n".join(lines)
    for i in range(0, len(text), 3500):
        await message.answer(text[i:i + 3500])


# ---------------------------------------------------------------------------
# /reload_token
# ---------------------------------------------------------------------------
@router.message(Command("reload_token"))
async def cmd_reload_token(message: Message) -> None:
    await message.answer("🔁 Forcing Exness re-auth…")
    ok = await force_reauth()
    await message.answer("✅ New JWT obtained." if ok else "❌ Re-auth failed — check logs.")

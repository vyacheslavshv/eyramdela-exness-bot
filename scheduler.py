"""Background re-checks.

Three jobs:

1. ``check_pending_users``        — every PENDING_POLL_MINUTES, retry users
   waiting for activation.
2. ``recheck_verified_users``     — every RECHECK_INTERVAL_HOURS, re-verify
   already-verified users (and warned ones), kick on partner change /
   inactivity / withdraw-everything.
3. ``daily_cleanup``               — once a day, prune very old AuditLog rows.

Critical safety rule (per the brief):
    On a transient API error -> DO NOT KICK. Only act on a definitive
    negative answer. Every API failure increments the user's
    ``consecutive_api_errors`` for visibility.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from config import (
    ADMIN_IDS,
    CHANNEL_ID,
    INACTIVITY_KICK_DAYS,
    INACTIVITY_WARN_DAYS,
    MIN_DEPOSIT_USD,
    PENDING_AUTO_GIVEUP_HOURS,
    PENDING_POLL_MINUTES,
    RECHECK_INTERVAL_HOURS,
    WARNING_GRACE_DAYS,
)
from exness_api import ClientSnapshot, fetch_snapshot, is_activated
from models import AuditLog, User
from utils import utcnow


scheduler = AsyncIOScheduler()


# Stagger requests so we don't hammer the API in one burst.
_PER_REQUEST_DELAY = 0.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _audit(telegram_id: int, event: str, detail: str | None = None) -> None:
    try:
        await AuditLog.create(telegram_id=telegram_id, event=event, detail=detail)
    except Exception as e:
        logger.warning(f"audit write failed: {e}")


async def _persist_snapshot(user: User, snap: ClientSnapshot) -> None:
    user.last_check_at = utcnow()
    user.last_client_status = snap.client_status
    try:
        user.last_progress_flags = json.dumps(list(snap.progress_flags))
    except Exception:
        user.last_progress_flags = "[]"
    try:
        user.last_deposit_total = Decimal(str(round(snap.deposit_total or 0, 2)))
    except Exception:
        user.last_deposit_total = Decimal("0")
    user.last_trade_at = snap.last_trade_at
    user.consecutive_api_errors = 0
    await user.save()


async def _record_api_error(user: User) -> None:
    user.consecutive_api_errors = (user.consecutive_api_errors or 0) + 1
    user.last_check_at = utcnow()
    await user.save()


async def _safe_send(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except Exception as e:
        logger.warning(f"send_message to {chat_id} failed: {e}")


async def _admin_notify(bot: Bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        await _safe_send(bot, admin_id, text)


async def _create_invite(bot: Bot, telegram_id: int) -> str | None:
    if not CHANNEL_ID:
        return None
    try:
        link = await bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            name=f"vip-{telegram_id}",
            expire_date=utcnow() + timedelta(hours=24),
        )
        return link.invite_link
    except Exception as e:
        logger.error(f"create_chat_invite_link failed for {telegram_id}: {e}")
        return None


async def _kick_from_channel(bot: Bot, telegram_id: int) -> None:
    """ban + unban → user is removed but can re-join later if they re-qualify."""
    if not CHANNEL_ID:
        return
    try:
        await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=telegram_id)
    except Exception as e:
        logger.warning(f"ban_chat_member {telegram_id} failed: {e}")
        return
    await asyncio.sleep(0.3)
    try:
        await bot.unban_chat_member(
            chat_id=CHANNEL_ID, user_id=telegram_id, only_if_banned=True
        )
    except Exception as e:
        logger.warning(f"unban_chat_member {telegram_id} failed: {e}")


async def _mark_kicked(user: User, event: str, detail: str | None = None) -> None:
    await User.filter(id=user.id).update(status="kicked", kicked_at=utcnow())
    await _audit(user.telegram_id, event, detail)


# ---------------------------------------------------------------------------
# Job 1 — pending users
# ---------------------------------------------------------------------------
async def check_pending_users(bot: Bot) -> None:
    # Auto-poll only users who recently entered pending. Anyone who's been
    # pending past the giveup window is left alone — they can resume by
    # tapping "Re-check now" or sending /start, which resets the window.
    cutoff = utcnow() - timedelta(hours=max(0.1, float(PENDING_AUTO_GIVEUP_HOURS)))
    pending = await User.filter(
        status="pending", exness_uid__not_isnull=True
    ).all()
    fresh = [
        u for u in pending if (u.pending_since or u.started_at) and
        (u.pending_since or u.started_at) > cutoff
    ]
    if not fresh:
        if pending:
            logger.debug(
                f"scheduler: {len(pending)} pending user(s) but all past "
                f"the {PENDING_AUTO_GIVEUP_HOURS}h giveup window"
            )
        return
    logger.debug(
        f"scheduler: {len(fresh)} fresh pending user(s) to re-check "
        f"({len(pending) - len(fresh)} skipped, past giveup window)"
    )

    for user in fresh:
        try:
            snap = await fetch_snapshot(user.exness_uid)
        except Exception as e:
            logger.error(f"fetch_snapshot crashed for {user.telegram_id}: {e}")
            snap = None

        if snap is None:
            await _record_api_error(user)
            await asyncio.sleep(_PER_REQUEST_DELAY)
            continue

        # User bailed before activating — clean up.
        if not snap.under_partner or snap.client_status in ("LEFT",):
            await _mark_kicked(
                user, "pending_left",
                f"under_partner={snap.under_partner} status={snap.client_status}",
            )
            await _safe_send(
                bot, user.telegram_id,
                "❌ We can no longer find your Exness account under our partner.\n\n"
                "If this is a mistake, please re-verify from /start.",
            )
            await asyncio.sleep(_PER_REQUEST_DELAY)
            continue

        await _persist_snapshot(user, snap)

        if is_activated(snap.progress_flags, snap.deposit_total):
            invite = await _create_invite(bot, user.telegram_id)
            await User.filter(id=user.id).update(
                status="verified", verified_at=utcnow()
            )
            await _audit(user.telegram_id, "verified_via_pending_poll")
            if invite:
                await _safe_send(
                    bot, user.telegram_id,
                    "✅ You're verified!\n\n"
                    "Your private invite link (single-use, 24h):\n\n"
                    f"{invite}\n\n"
                    "Welcome to the VIP.",
                )
            else:
                await _safe_send(
                    bot, user.telegram_id,
                    "✅ You're verified! Could not auto-generate an invite "
                    "link — please contact the admin to be added manually.",
                )
        await asyncio.sleep(_PER_REQUEST_DELAY)


# ---------------------------------------------------------------------------
# Job 2 — recheck verified / warned users
# ---------------------------------------------------------------------------
async def recheck_one_user(bot: Bot, user: User, now: datetime | None = None) -> str:
    """Re-verify a single verified/warned user and apply the result
    (kick / warn / restore / refresh snapshot). Returns a short status
    string for logging / the admin /recheck command.

    Used both by the periodic `recheck_verified_users` loop and by the
    admin `/recheck` command (so the operator can test the kick path
    without waiting for the scheduler).
    """
    if now is None:
        now = utcnow()

    try:
        snap = await fetch_snapshot(user.exness_uid)
    except Exception as e:
        logger.error(f"fetch_snapshot crashed for {user.telegram_id}: {e}")
        snap = None

    if snap is None:
        await _record_api_error(user)
        return "api_error (no action)"

    # ---- partner change / left ----
    if not snap.under_partner or snap.client_status in ("LEFT", "CHANGING"):
        reason = (
            "not_under_partner" if not snap.under_partner
            else f"client_status={snap.client_status}"
        )
        await _kick_from_channel(bot, user.telegram_id)
        await _mark_kicked(user, "kicked_partner_changed", reason)
        await _safe_send(
            bot, user.telegram_id,
            "❌ You've been removed from the VIP channel.\n\n"
            "Reason: your Exness account is no longer registered under our partner. "
            "If this is a mistake, please re-verify from /start.",
        )
        await _admin_notify(
            bot,
            f"🚪 Kicked @{user.username or '—'} ({user.telegram_id}) "
            f"— partner change ({reason})",
        )
        return f"kicked_partner_changed ({reason})"

    # ---- no longer meets the activation gate → kick ----
    # `is_activated` requires a real first-time deposit (ftd_received,
    # which is sticky on Exness's side once true). So this only ever
    # catches accounts that slipped in without one — e.g. a no-deposit
    # bonus trade — never a genuine depositor. We check regardless of
    # client_status: an account that doesn't meet the gate shouldn't be
    # in the channel whether Exness marks it ACTIVE or INACTIVE.
    # (LEFT / CHANGING are already handled above.)
    if not is_activated(snap.progress_flags, snap.deposit_total):
        await _kick_from_channel(bot, user.telegram_id)
        await _mark_kicked(
            user, "kicked_not_activated",
            f"flags={snap.progress_flags} deposit={snap.deposit_total}",
        )
        await _safe_send(
            bot, user.telegram_id,
            "❌ You've been removed from the VIP channel.\n\n"
            f"Reason: your Exness account does not meet the activation "
            f"requirements — a first deposit of ${int(MIN_DEPOSIT_USD)} "
            "or more is required. Make the deposit, then re-verify from "
            "/start to rejoin.",
        )
        await _admin_notify(
            bot,
            f"🚫 Kicked @{user.username or '—'} ({user.telegram_id}) "
            f"— not activated (no qualifying deposit).",
        )
        return "kicked_not_activated"

    # ---- balance ≈ 0 after a real deposit history → withdrew everything ----
    # Trust the ftd_received flag as the truth source: numeric
    # deposit_amount / client_balance can be the placeholder "1" that
    # Exness returns for never-deposited accounts. Once a user has
    # ftd_received=true, an empty balance signals a withdrawal.
    had_deposits = "ftd_received" in (snap.progress_flags or [])
    if had_deposits and (snap.balance or 0) < 1.0:
        await _kick_from_channel(bot, user.telegram_id)
        await _mark_kicked(
            user, "kicked_zero_balance",
            f"balance={snap.balance}, dep_total={snap.deposit_total}",
        )
        await _safe_send(
            bot, user.telegram_id,
            "❌ You've been removed from the VIP channel.\n\n"
            "Reason: your Exness account balance is empty. "
            "Re-fund the account and re-verify from /start to rejoin.",
        )
        await _admin_notify(
            bot,
            f"💸 Kicked @{user.username or '—'} ({user.telegram_id}) "
            f"— zero balance.",
        )
        return "kicked_zero_balance"

    # ---- inactivity flow ----
    # Conservative rule: if Exness has not given us a last_trade
    # timestamp, do NOT warn or kick on inactivity. A user who
    # qualified by deposit-only would otherwise be kicked
    # immediately even though they're a paying customer.
    last_trade = snap.last_trade_at
    days_since_trade: float | None
    if last_trade:
        days_since_trade = (now - last_trade).total_seconds() / 86400
    else:
        days_since_trade = None

    # Recovery: warned → active again
    if user.status == "warned" and days_since_trade is not None and \
            days_since_trade < INACTIVITY_WARN_DAYS and snap.client_status == "ACTIVE":
        await User.filter(id=user.id).update(
            status="verified", last_warning_at=None
        )
        await _audit(user.telegram_id, "recovered_from_warning")
        await _safe_send(
            bot, user.telegram_id,
            "✅ Welcome back — we see your account is active again.\n\n"
            "You're all good in the VIP channel.",
        )
        await _persist_snapshot(user, snap)
        return "recovered_from_warning"

    # Warned + grace expired + still inactive → kick.
    # Only kick if we have a real days_since_trade — never on
    # missing-timestamp data.
    if user.status == "warned" and user.last_warning_at and \
            (now - user.last_warning_at).total_seconds() / 86400 \
            >= WARNING_GRACE_DAYS and \
            days_since_trade is not None and \
            days_since_trade >= INACTIVITY_WARN_DAYS:
        await _kick_from_channel(bot, user.telegram_id)
        await _mark_kicked(
            user, "kicked_inactive",
            f"days_since_trade={days_since_trade}",
        )
        await _safe_send(
            bot, user.telegram_id,
            "❌ You've been removed from the VIP channel due to "
            "inactivity.\n\nPlace a trade and /start the bot to rejoin.",
        )
        await _admin_notify(
            bot,
            f"😴 Kicked @{user.username or '—'} ({user.telegram_id}) "
            f"— inactivity.",
        )
        return "kicked_inactive"

    # Verified + just crossed the warn threshold → send heads-up
    if user.status == "verified" and days_since_trade is not None and \
            days_since_trade >= INACTIVITY_WARN_DAYS:
        await User.filter(id=user.id).update(
            status="warned", last_warning_at=now
        )
        await _audit(
            user.telegram_id, "warning_sent",
            f"days_since_trade={days_since_trade:.1f}",
        )
        await _safe_send(
            bot, user.telegram_id,
            "⚠️ Heads up — inactivity detected\n\n"
            f"We haven't seen any trading activity on your Exness account "
            f"for ~{int(days_since_trade)} days. To stay in the VIP "
            f"channel, place at least one trade in the next "
            f"{WARNING_GRACE_DAYS} day(s), or we'll have to remove you.\n\n"
            "Re-joining is easy — just /start the bot again after you trade.",
        )
        await _persist_snapshot(user, snap)
        return "warning_sent"

    await _persist_snapshot(user, snap)
    return "ok (still verified)"


async def recheck_verified_users(bot: Bot) -> None:
    rows = await User.filter(
        status__in=["verified", "warned"], exness_uid__not_isnull=True
    ).all()
    if not rows:
        return
    logger.debug(f"scheduler: re-checking {len(rows)} verified/warned user(s)")
    now = utcnow()
    for user in rows:
        try:
            await recheck_one_user(bot, user, now)
        except Exception as e:
            logger.error(f"recheck_one_user crashed for {user.telegram_id}: {e}")
        await asyncio.sleep(_PER_REQUEST_DELAY)


# ---------------------------------------------------------------------------
# Job 3 — daily cleanup
# ---------------------------------------------------------------------------
async def daily_cleanup(bot: Bot) -> None:
    cutoff = utcnow() - timedelta(days=90)
    deleted = await AuditLog.filter(created_at__lt=cutoff).delete()
    if deleted:
        logger.info(f"daily_cleanup: deleted {deleted} old audit rows")


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
def start_scheduler(bot: Bot) -> None:
    scheduler.add_job(
        check_pending_users,
        IntervalTrigger(minutes=max(1, float(PENDING_POLL_MINUTES))),
        args=[bot],
        id="pending_poll",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        recheck_verified_users,
        IntervalTrigger(hours=max(0.05, float(RECHECK_INTERVAL_HOURS))),
        args=[bot],
        id="recheck_verified",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        daily_cleanup,
        CronTrigger(hour=3, minute=0),
        args=[bot],
        id="daily_cleanup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        f"Scheduler started "
        f"(pending poll: {PENDING_POLL_MINUTES}m, "
        f"recheck: {RECHECK_INTERVAL_HOURS}h, "
        f"warn>{INACTIVITY_WARN_DAYS}d, kick>{INACTIVITY_KICK_DAYS}d, "
        f"min_deposit=${int(MIN_DEPOSIT_USD)})"
    )

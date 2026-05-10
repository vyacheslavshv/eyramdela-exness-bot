"""User-facing /start, FSM verify flow, callbacks."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from loguru import logger

from config import (
    ADMIN_IDS,
    BRAND_NAME,
    CHANNEL_ID,
    EXNESS_REFERRAL_LINK,
    MIN_DEPOSIT_USD,
    PENDING_POLL_MINUTES,
)
from exness_api import fetch_snapshot, is_activated
from models import AuditLog, User
from utils import normalize_phone, utcnow

router = Router()


# ---------------------------------------------------------------------------
# FSM states for the verify funnel
# ---------------------------------------------------------------------------
class VerifyState(StatesGroup):
    awaiting_phone = State()
    awaiting_uid = State()


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------
def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Get Free VIP Access", callback_data="start_verify")],
        [InlineKeyboardButton(text="ℹ️ How It Works", callback_data="how_it_works")],
        [InlineKeyboardButton(text="📊 Check My Status", callback_data="my_status")],
    ])


def kb_back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Get Free VIP Access", callback_data="start_verify")],
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")],
    ])


def kb_phone_request() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Share my phone", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Tap the button to share your phone",
    )


def kb_register_or_recheck() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if EXNESS_REFERRAL_LINK:
        rows.append([
            InlineKeyboardButton(text="🟢 Register on Exness", url=EXNESS_REFERRAL_LINK)
        ])
    rows.append([
        InlineKeyboardButton(text="🔁 I already registered, re-check", callback_data="start_verify")
    ])
    rows.append([
        InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_pending_help() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if EXNESS_REFERRAL_LINK:
        rows.append([
            InlineKeyboardButton(text="🟢 Open Exness", url=EXNESS_REFERRAL_LINK)
        ])
    rows.append([
        InlineKeyboardButton(text="🔁 Re-check now", callback_data="recheck_pending")
    ])
    rows.append([
        InlineKeyboardButton(text="📊 My Status", callback_data="my_status")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_verified(invite_link: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if invite_link:
        rows.append([
            InlineKeyboardButton(text="🚀 Open VIP Channel", url=invite_link)
        ])
    rows.append([
        InlineKeyboardButton(text="📊 My Status", callback_data="my_status")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_verify")],
    ])


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------
def welcome_text(first_name: str | None) -> str:
    name = first_name or "there"
    return (
        f"👋 Welcome to {BRAND_NAME}, {name}!\n\n"
        "Free lifetime access to our private VIP signals channel — "
        "no subscription, no fees. All you need is an Exness account "
        "registered under our partner code.\n\n"
        "Tap below to start."
    )


HOW_IT_WORKS_TEXT = (
    "ℹ️ How It Works\n\n"
    "1. Share your phone number (used only for partner verification).\n"
    "2. Send your Exness account ID.\n"
    "3. We'll check that your account is registered under our partner.\n"
    f"4. Make your first trade OR a deposit ≥ ${int(MIN_DEPOSIT_USD)} to activate.\n"
    "5. Get an invite link to the VIP channel — instantly.\n\n"
    "We re-check your account periodically. As long as it stays under our "
    "partner and you keep trading, you keep your VIP access."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _safe_edit(callback: CallbackQuery, text: str,
                     reply_markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await callback.message.answer(text, reply_markup=reply_markup)


async def _audit(telegram_id: int, event: str, detail: str | None = None) -> None:
    try:
        await AuditLog.create(telegram_id=telegram_id, event=event, detail=detail)
    except Exception as e:
        logger.warning(f"audit log write failed: {e}")


async def _send_main_menu(target_message: Message, first_name: str | None) -> None:
    await target_message.answer(
        welcome_text(first_name),
        reply_markup=kb_main_menu(),
    )


async def _generate_invite(bot: Bot, telegram_id: int) -> str | None:
    if not CHANNEL_ID:
        return None
    try:
        link = await bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            name=f"vip-{telegram_id}",
        )
        return link.invite_link
    except Exception as e:
        logger.error(f"create_chat_invite_link failed for {telegram_id}: {e}")
        return None


def _serialize_flags(flags: list[str]) -> str:
    try:
        return json.dumps(list(flags))
    except Exception:
        return "[]"


async def _persist_snapshot(user: User, snapshot) -> None:
    """Write the latest API snapshot back into the User row."""
    user.last_check_at = utcnow()
    user.last_client_status = snapshot.client_status
    user.last_progress_flags = _serialize_flags(snapshot.progress_flags)
    try:
        user.last_deposit_total = Decimal(str(round(snapshot.deposit_total or 0, 2)))
    except Exception:
        user.last_deposit_total = Decimal("0")
    user.last_trade_at = snapshot.last_trade_at
    user.consecutive_api_errors = 0
    await user.save()


async def _record_api_error(user: User) -> None:
    user.consecutive_api_errors = (user.consecutive_api_errors or 0) + 1
    user.last_check_at = utcnow()
    await user.save()


async def _verify_and_route(user: User, message: Message, bot: Bot) -> None:
    """Run a verification pass for this user and reply with the right copy."""
    snapshot = await fetch_snapshot(user.exness_uid)

    if snapshot is None:
        await _record_api_error(user)
        await message.answer(
            "⚠️ We're having trouble reaching Exness right now.\n\n"
            "Please try again in a few minutes — we'll re-check automatically.",
            reply_markup=kb_pending_help(),
        )
        return

    if not snapshot.under_partner:
        await user.update_from_dict({
            "status": "onboarding",
            "last_client_status": None,
        }).save()
        await _audit(user.telegram_id, "not_under_partner", f"uid={user.exness_uid}")
        await message.answer(
            "❌ This Exness account is not registered under our partner yet.\n\n"
            "Make sure you used our referral link when signing up. If you "
            "already have an Exness account, you can switch your partner "
            "from inside Exness and then re-check.",
            reply_markup=kb_register_or_recheck(),
        )
        return

    activated = is_activated(snapshot.progress_flags, snapshot.deposit_total)
    await _persist_snapshot(user, snapshot)

    if activated:
        invite = await _generate_invite(bot, user.telegram_id)
        await user.update_from_dict({
            "status": "verified",
            "verified_at": utcnow(),
        }).save()
        await _audit(user.telegram_id, "verified", f"uid={user.exness_uid}")
        if invite:
            await message.answer(
                "✅ You're verified!\n\n"
                "Welcome to the VIP. Here's your private invite link "
                "(single-use, expires in 24h):\n\n"
                f"{invite}\n\n"
                "Trade well. We'll re-check your status periodically and "
                "you'll stay in as long as your account is active under "
                "our partnership.",
                reply_markup=kb_verified(invite),
            )
        else:
            await message.answer(
                "✅ You're verified!\n\n"
                "Could not auto-generate an invite link — please contact "
                "the admin so they can add you manually.",
                reply_markup=kb_verified(None),
            )
    else:
        await user.update_from_dict({"status": "pending"}).save()
        await _audit(
            user.telegram_id,
            "pending_activation",
            f"flags={snapshot.progress_flags} deposit={snapshot.deposit_total}",
        )
        poll = max(1, int(PENDING_POLL_MINUTES))
        await message.answer(
            "🟡 Almost there!\n\n"
            "Your Exness account is registered under our partner, but it's "
            "not yet activated. To activate, do one of the following:\n\n"
            f"• Place your first trade, or\n"
            f"• Make a deposit of ${int(MIN_DEPOSIT_USD)} or more.\n\n"
            f"We'll auto-check every ~{poll} minutes and let you know when "
            "you're in.",
            reply_markup=kb_pending_help(),
        )


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
ADMIN_PANEL_TEXT = (
    "🛠 Admin panel\n\n"
    "Quick reference (full list via /help):\n"
    "/stats — counts per status\n"
    "/user <telegram_id|UID> — user info\n"
    "/check <UID> — manual API check\n"
    "/kick <telegram_id> — manual kick\n"
    "/unflag <telegram_id> — restore user\n"
    "/users [status] [page] — paginated list\n"
    "/broadcast <text> — DM verified users\n"
    "/broadcast_channel <text> — post to VIP channel\n"
    "/export — CSV dump\n"
    "/audit [N] — last N audit events\n"
    "/reload_token — force JWT re-auth"
)


@router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    tg = message.from_user

    if tg.id in ADMIN_IDS:
        await message.answer(ADMIN_PANEL_TEXT)
        return

    user, _ = await User.get_or_create(
        telegram_id=tg.id,
        defaults={
            "username": tg.username,
            "first_name": tg.first_name,
            "status": "onboarding",
        },
    )
    await User.filter(telegram_id=tg.id).update(
        username=tg.username, first_name=tg.first_name
    )

    if user.status == "verified":
        await message.answer(
            f"✅ You're already verified, {tg.first_name or 'friend'}!\n\n"
            "You have lifetime access to the VIP channel as long as your "
            "Exness account stays active under our partner.",
            reply_markup=kb_verified(None),
        )
        return

    if user.status == "pending":
        await message.answer(
            "🟡 You're already in the queue.\n\n"
            "We're waiting for your account to activate (first trade or "
            f"first deposit ≥ ${int(MIN_DEPOSIT_USD)}). Once it does, "
            "we'll DM your invite link.",
            reply_markup=kb_pending_help(),
        )
        return

    if user.status in ("warned", "kicked"):
        await message.answer(
            "👋 Welcome back!\n\n"
            "You can re-verify your Exness account below to regain access.",
            reply_markup=kb_main_menu(),
        )
        return

    await message.answer(welcome_text(tg.first_name), reply_markup=kb_main_menu())


# ---------------------------------------------------------------------------
# Callback: How It Works
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "how_it_works")
async def cb_how_it_works(callback: CallbackQuery) -> None:
    await _safe_edit(callback, HOW_IT_WORKS_TEXT, reply_markup=kb_back_to_menu())
    await callback.answer()


# ---------------------------------------------------------------------------
# Callback: Back to Menu
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _safe_edit(
        callback, welcome_text(callback.from_user.first_name),
        reply_markup=kb_main_menu(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Callback: Cancel verify
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "cancel_verify")
async def cb_cancel_verify(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await callback.message.answer(
            "Cancelled.",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception:
        pass
    await _safe_edit(
        callback, welcome_text(callback.from_user.first_name),
        reply_markup=kb_main_menu(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Callback: My Status
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "my_status")
async def cb_my_status(callback: CallbackQuery) -> None:
    user = await User.filter(telegram_id=callback.from_user.id).first()
    if not user:
        await _safe_edit(
            callback,
            welcome_text(callback.from_user.first_name),
            reply_markup=kb_main_menu(),
        )
        await callback.answer()
        return

    label = {
        "onboarding": "👋 Not yet verified",
        "pending": "🟡 Pending activation",
        "verified": "✅ Verified — VIP active",
        "warned": "⚠️ Warning — please trade soon",
        "kicked": "❌ Removed — re-verify to rejoin",
    }.get(user.status, user.status)

    flags = user.last_progress_flags or "[]"
    try:
        flags_list = json.loads(flags)
    except Exception:
        flags_list = []

    summary = (
        f"📊 Your Status\n\n"
        f"State: {label}\n"
        f"Exness UID: {user.exness_uid or '—'}\n"
        f"Last partner status: {user.last_client_status or '—'}\n"
        f"Last progress: {', '.join(flags_list) if flags_list else '—'}\n"
        f"Last deposit total: "
        f"${float(user.last_deposit_total or 0):.2f}\n"
    )
    await _safe_edit(callback, summary, reply_markup=kb_back_to_menu())
    await callback.answer()


# ---------------------------------------------------------------------------
# Callback: Start verify (entry to phone request)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "start_verify")
async def cb_start_verify(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    user = await User.filter(telegram_id=callback.from_user.id).first()

    if user and user.status == "verified":
        await _safe_edit(
            callback,
            "✅ You're already verified.\n\nNothing to do — enjoy the VIP channel.",
            reply_markup=kb_verified(None),
        )
        await callback.answer()
        return

    # Already gave us phone+UID → just re-run the check.
    if user and user.exness_uid and user.phone:
        await callback.answer("Re-checking…")
        await _safe_edit(callback, "🔁 Re-checking your Exness account…")
        await _verify_and_route(user, callback.message, bot)
        return

    # If they have phone but not UID, jump straight to UID step.
    if user and user.phone:
        await state.set_state(VerifyState.awaiting_uid)
        await _safe_edit(
            callback,
            "🔑 Send me your Exness account ID (the trading account number "
            "you see in your Exness dashboard, e.g. 12345678).",
            reply_markup=kb_cancel(),
        )
        await callback.answer()
        return

    # Otherwise start with phone.
    await state.set_state(VerifyState.awaiting_phone)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "📱 First, please share your phone number.\n\n"
        "It's used for partner verification and admin contact only — "
        "we do not share it with anyone else.",
        reply_markup=kb_phone_request(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Callback: Re-check pending now
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "recheck_pending")
async def cb_recheck_pending(callback: CallbackQuery, bot: Bot) -> None:
    user = await User.filter(telegram_id=callback.from_user.id).first()
    if not user or not user.exness_uid:
        await callback.answer("No UID on file yet.", show_alert=True)
        return
    await callback.answer("Re-checking…")
    await _verify_and_route(user, callback.message, bot)


# ---------------------------------------------------------------------------
# FSM: receive phone
# ---------------------------------------------------------------------------
@router.message(StateFilter(VerifyState.awaiting_phone), F.contact)
async def on_phone_contact(message: Message, state: FSMContext) -> None:
    contact = message.contact
    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer(
            "Please share your own phone number using the button below.",
            reply_markup=kb_phone_request(),
        )
        return

    phone = normalize_phone(contact.phone_number)
    await User.filter(telegram_id=message.from_user.id).update(phone=phone)

    await state.set_state(VerifyState.awaiting_uid)
    await message.answer(
        "✅ Got it.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        "🔑 Now send me your Exness account ID (the trading account "
        "number you see in your Exness dashboard, e.g. 12345678).",
        reply_markup=kb_cancel(),
    )


@router.message(StateFilter(VerifyState.awaiting_phone), F.text)
async def on_phone_text(message: Message, state: FSMContext) -> None:
    """Some users won't tap the contact button — accept typed phone too."""
    phone = normalize_phone(message.text)
    if not phone or len(phone) < 8:
        await message.answer(
            "That doesn't look like a valid phone number.\n\n"
            "Please tap the \"Share my phone\" button below, "
            "or type the number in international format (e.g. +14155551234).",
            reply_markup=kb_phone_request(),
        )
        return
    await User.filter(telegram_id=message.from_user.id).update(phone=phone)
    await state.set_state(VerifyState.awaiting_uid)
    await message.answer("✅ Got it.", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "🔑 Now send me your Exness account ID (the trading account "
        "number you see in your Exness dashboard, e.g. 12345678).",
        reply_markup=kb_cancel(),
    )


# ---------------------------------------------------------------------------
# FSM: receive UID
# ---------------------------------------------------------------------------
@router.message(StateFilter(VerifyState.awaiting_uid), F.text)
async def on_uid_input(message: Message, state: FSMContext, bot: Bot) -> None:
    raw = (message.text or "").strip()
    uid = "".join(ch for ch in raw if ch.isdigit())
    if not uid or len(uid) < 4:
        await message.answer(
            "That doesn't look like a valid Exness account ID.\n\n"
            "It should be a number — e.g. 12345678. Try again, or tap Cancel.",
            reply_markup=kb_cancel(),
        )
        return

    # Prevent two Telegram users from claiming the same UID.
    other = await User.filter(exness_uid=uid).exclude(telegram_id=message.from_user.id).first()
    if other:
        await message.answer(
            "⚠️ This Exness account is already linked to another Telegram user.\n\n"
            "If this is your account, please contact the admin.",
            reply_markup=kb_back_to_menu(),
        )
        await state.clear()
        return

    await User.filter(telegram_id=message.from_user.id).update(exness_uid=uid)
    await state.clear()

    user = await User.filter(telegram_id=message.from_user.id).first()
    if not user:
        return

    await message.answer("🔎 Checking your Exness account…")
    await _verify_and_route(user, message, bot)


# ---------------------------------------------------------------------------
# /help — for users only; admin /help is handled in handlers/admin.py.
# ---------------------------------------------------------------------------
@router.message(Command("help"), F.chat.type == "private", ~F.from_user.id.in_(ADMIN_IDS))
async def cmd_help(message: Message, state: FSMContext) -> None:
    await cmd_start(message, state)

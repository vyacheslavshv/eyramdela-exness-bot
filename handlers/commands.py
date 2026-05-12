"""User-facing /start, the Join-VIP funnel (email → phone → Exness ID),
and all main-menu callbacks. Layout follows the client's spec sheet."""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
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
    ACTIVATION_REQUIRE_TRADE,
    ADMIN_IDS,
    BRAND_NAME,
    CHANNEL_ID,
    EXNESS_DEPOSIT_URL,
    EXNESS_PA_URL,
    EXNESS_PARTNER_CODE,
    EXNESS_REFERRAL_LINK,
    MIN_DEPOSIT_USD,
    PENDING_AUTO_GIVEUP_HOURS,
    PENDING_POLL_MINUTES,
)
from exness_api import fetch_snapshot, is_activated
from models import AuditLog, User
from utils import normalize_email, normalize_phone, utcnow

router = Router()


# ---------------------------------------------------------------------------
# FSM states — the Join-VIP funnel collects email → phone → Exness ID.
# ---------------------------------------------------------------------------
class VerifyState(StatesGroup):
    awaiting_email = State()
    awaiting_phone = State()
    awaiting_uid = State()


# ---------------------------------------------------------------------------
# Small helpers used to interpolate the client's templated copy.
# ---------------------------------------------------------------------------
def _partner_link_line() -> str:
    return EXNESS_REFERRAL_LINK or "(partner link — ask the admin)"


def _partner_code_html() -> str:
    if EXNESS_PARTNER_CODE:
        return f"<code>{html.escape(EXNESS_PARTNER_CODE)}</code> (tap to copy)"
    return "(ask the admin for the partner code)"


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------
def kb_main_menu() -> InlineKeyboardMarkup:
    """Exact button order requested by the client:
    How It Works → Register on Exness → Join VIP for Free → Check Status."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 How It Works", callback_data="how_it_works")],
        [InlineKeyboardButton(text="🟢 Register on Exness", callback_data="register_exness")],
        [InlineKeyboardButton(text="🚀 Join VIP for Free", callback_data="join_vip")],
        [InlineKeyboardButton(text="📊 Check Status", callback_data="check_status")],
    ])


def kb_back_to_menu(extra_join: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if extra_join:
        rows.append([
            InlineKeyboardButton(text="🚀 Join VIP for Free", callback_data="join_vip")
        ])
    rows.append([
        InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_register_screen() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if EXNESS_REFERRAL_LINK:
        rows.append([
            InlineKeyboardButton(text="🟢 Register on Exness", url=EXNESS_REFERRAL_LINK)
        ])
    rows.append([
        InlineKeyboardButton(text="🚀 Join VIP for Free", callback_data="join_vip")
    ])
    rows.append([
        InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_join_vip_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yes, My Account Is Under You", callback_data="acc_under")],
        [InlineKeyboardButton(text="❌ My Account Is NOT Under You", callback_data="acc_not_under")],
        [InlineKeyboardButton(text="📊 Check My Status", callback_data="check_status")],
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")],
    ])


def kb_switch_partner() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if EXNESS_REFERRAL_LINK:
        rows.append([
            InlineKeyboardButton(text="🟢 Open Partner Link", url=EXNESS_REFERRAL_LINK)
        ])
    rows.append([
        InlineKeyboardButton(text="📊 Check My Status", callback_data="check_status")
    ])
    rows.append([
        InlineKeyboardButton(text="🆕 Create New Exness Account", callback_data="create_new_exness")
    ])
    rows.append([
        InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_create_new() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if EXNESS_REFERRAL_LINK:
        rows.append([
            InlineKeyboardButton(text="🟢 Open Partner Link", url=EXNESS_REFERRAL_LINK)
        ])
    rows.append([
        InlineKeyboardButton(text="📊 Check My Status", callback_data="check_status")
    ])
    rows.append([
        InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_not_connected() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔀 Switch Partner", callback_data="acc_not_under")],
        [InlineKeyboardButton(text="✏️ I entered the wrong ID", callback_data="edit_uid")],
        [InlineKeyboardButton(text="📊 Check My Status", callback_data="check_status")],
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")],
    ])


def kb_pending_help() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if EXNESS_DEPOSIT_URL:
        rows.append([
            InlineKeyboardButton(text="💵 Make a Deposit", url=EXNESS_DEPOSIT_URL)
        ])
    if EXNESS_PA_URL:
        rows.append([
            InlineKeyboardButton(text="📈 Open Exness (Trade)", url=EXNESS_PA_URL)
        ])
    rows.append([
        InlineKeyboardButton(text="🔁 Re-check now", callback_data="recheck_pending")
    ])
    rows.append([
        InlineKeyboardButton(text="✏️ I entered the wrong ID", callback_data="edit_uid")
    ])
    rows.append([
        InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_verified(invite_link: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if invite_link:
        rows.append([
            InlineKeyboardButton(text="🚀 Open VIP Channel", url=invite_link)
        ])
    rows.append([
        InlineKeyboardButton(text="🔗 Get Invite Link Again", callback_data="new_invite")
    ])
    rows.append([
        InlineKeyboardButton(text="📊 Check My Status", callback_data="check_status")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_status_no_uid() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Join VIP for Free", callback_data="join_vip")],
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")],
    ])


def kb_phone_request() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Share my phone", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Tap the button to share your phone",
    )


def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_verify")],
    ])


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------
def welcome_text(first_name: str | None) -> str:
    # "Keep the current welcome message exactly the same."
    name = first_name or "there"
    return (
        f"👋 Welcome to {BRAND_NAME}, {name}!\n\n"
        "Free lifetime access to our private VIP signals channel — "
        "no subscription, no fees. All you need is an Exness account "
        "registered under our partner code.\n\n"
        "Tap below to start."
    )


HOW_IT_WORKS_TEXT = (
    "🔥 HOW IT WORKS\n\n"
    "1️⃣ Share your email address\n"
    "2️⃣ Share your phone number\n"
    "3️⃣ Share your Exness ID (Trading Account Number)\n"
    "4️⃣ Fund your account to activate it. Empty / never-funded accounts "
    "don't get access.\n"
    + (f"💰 Minimum deposit: ${int(MIN_DEPOSIT_USD)}\n"
       if MIN_DEPOSIT_USD > 10 else "💰 Just make your first deposit (any amount).\n")
    + "5️⃣ Once verified, you'll receive your VIP invite link.\n\n"
    "⚠️ Important:\n"
    "We periodically recheck all accounts. As long as your account "
    "remains connected under our partner link, you'll continue "
    "enjoying VIP access and all community benefits.\n\n"
    "💎 Stay loyal & stay profitable."
)


def register_text() -> str:
    return (
        "📝 Create Your Exness Account\n\n"
        "To join our VIP community for FREE, register using our official "
        "partner link below:\n\n"
        f"👉 {_partner_link_line()}\n\n"
        "After registration, return here and tap \"Join VIP for Free\"."
    )


JOIN_VIP_CHOICE_TEXT = "❓ Do you already have an Exness account?"


def switch_partner_text() -> str:
    return (
        f"🔥 How to Switch to {BRAND_NAME} on Exness\n\n"
        "Follow these steps carefully to join for FREE:\n\n"
        "1️⃣ Log in to your Exness account.\n\n"
        "2️⃣ Open Live Chat and type:\n"
        "“Change Partner”\n\n"
        "3️⃣ When asked for the purpose, select:\n"
        "Signals / Education\n\n"
        "4️⃣ Fill out the form using our partner link below:\n"
        f"👉 {_partner_link_line()}\n\n"
        "5️⃣ Wait for the approval email before taking any further action.\n\n"
        "6️⃣ AFTER APPROVAL, create a NEW Real MT4/MT5 trading account.\n\n"
        "7️⃣ Transfer your funds from the old trading account (if any) to "
        "the new one, then archive the old account.\n\n"
        "⚠️ Important:\n"
        "Your old account number may still remain under your previous "
        "partner until funds are moved into the newly created trading "
        "account. This is why creating a new account after approval is "
        "very important.\n\n"
        "✅ Once completed, return here and tap “Check My Status” for "
        "verification."
    )


def create_new_text() -> str:
    return (
        "🆕 Your account is currently not eligible for partner transfer.\n\n"
        "No worries — you can still join the VIP community by creating a "
        "NEW Exness account under our partner link.\n\n"
        "Exness allows you to create another account using:\n"
        "• The same personal details\n"
        "• The same identity verification\n"
        "• The same phone number\n\n"
        "⚠️ The only requirement: use a different email address during "
        "registration.\n\n"
        "STEPS TO FOLLOW\n\n"
        "1️⃣ Create a NEW Exness account using our partner link below:\n"
        f"👉 {_partner_link_line()}\n"
        f"   …or use Partner Code: {_partner_code_html()}\n\n"
        "2️⃣ Register using a different email address\n"
        "3️⃣ Complete verification\n"
        "4️⃣ Create a Real MT4/MT5 trading account\n"
        f"5️⃣ Deposit and place at least one trade to activate the account\n"
        "6️⃣ Return here and tap “Check My Status”\n\n"
        "Once verified, your VIP access will be approved automatically and "
        "you'll receive the invite link.\n\n"
        "🎉 Welcome to the community."
    )


EMAIL_PROMPT_TEXT = (
    "📧 Please enter the email address used for your Exness account."
)

PHONE_PROMPT_TEXT = "📱 Now share your phone number using the button below."

WHERE_TO_FIND_UID = (
    "📍 Where to find it:\n"
    "• Web — sign in at my.exness.com → “My Accounts”. Each trading "
    "account shows an 8-9 digit number (e.g. 12345678).\n"
    "• Mobile app — open the app → tap your account → the number above "
    "the balance.\n\n"
    "Send just the digits — not your email, password, or partner code."
)

UID_PROMPT_TEXT = (
    "🔑 Now send your Exness ID (Trading Account Number).\n\n"
    + WHERE_TO_FIND_UID
)

VERIFY_DELAY_TEXT = (
    "⏳ Verification can take a few minutes depending on Exness processing "
    "time. Please be patient while we confirm your account status."
)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
async def _safe_edit(callback: CallbackQuery, text: str,
                     reply_markup: InlineKeyboardMarkup | None = None,
                     parse_mode: str | None = None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        try:
            await callback.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            logger.warning(f"_safe_edit fallback failed: {e}")


async def _audit(telegram_id: int, event: str, detail: str | None = None) -> None:
    try:
        await AuditLog.create(telegram_id=telegram_id, event=event, detail=detail)
    except Exception as e:
        logger.warning(f"audit log write failed: {e}")


async def _ensure_user(tg) -> User:
    """Fetch (or create) the User row for a Telegram user, refreshing the
    cached profile fields. Guards against funnels looping forever if the
    user somehow reached a callback/FSM step without ever sending /start."""
    user, _ = await User.get_or_create(
        telegram_id=tg.id,
        defaults={
            "username": tg.username,
            "first_name": tg.first_name,
            "status": "onboarding",
        },
    )
    if user.username != tg.username or user.first_name != tg.first_name:
        user.username = tg.username
        user.first_name = tg.first_name
        await user.save()
    return user


async def _generate_invite(bot: Bot, telegram_id: int) -> str | None:
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


def _serialize_flags(flags: list[str]) -> str:
    try:
        return json.dumps(list(flags))
    except Exception:
        return "[]"


async def _persist_snapshot(user: User, snapshot) -> None:
    user.last_check_at = utcnow()
    user.last_client_status = snapshot.client_status
    user.last_progress_flags = _serialize_flags(snapshot.progress_flags)
    # last_deposit_total holds the Exness deposit *range-ID* (1–6), not a
    # dollar figure — see exness_api.bucket_label.
    try:
        user.last_deposit_total = Decimal(int(getattr(snapshot, "deposit_bucket", 0) or 0))
    except Exception:
        user.last_deposit_total = Decimal("0")
    user.last_trade_at = snapshot.last_trade_at
    user.consecutive_api_errors = 0

    canonical = getattr(snapshot, "client_uid", None)
    if canonical and user.exness_uid != canonical:
        clash = await User.filter(exness_uid=canonical).exclude(id=user.id).first()
        if not clash:
            user.exness_uid = canonical

    await user.save()


async def _record_api_error(user: User) -> None:
    user.consecutive_api_errors = (user.consecutive_api_errors or 0) + 1
    user.last_check_at = utcnow()
    await user.save()


async def _verify_and_route(user: User, message: Message, bot: Bot) -> None:
    """Run one verification pass and reply with the matching screen."""
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
            "❌ Your account is currently not connected under our partner "
            "link.\n\n"
            "To access the VIP community, complete the partner switch "
            "process first — or, if you mistyped, fix your Exness ID.",
            reply_markup=kb_not_connected(),
        )
        return

    activated = is_activated(snapshot.progress_flags, snapshot.deposit_bucket)
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
                "🎉 Congratulations!\n\n"
                "✅ VIP Access Approved\n\n"
                f"{invite}\n\n"
                "This invite link is single-use and expires in 24 hours. "
                "We re-check accounts periodically — stay under our partner "
                "link and you keep your access.\n\n"
                "Welcome to the community. 💎",
                reply_markup=kb_verified(invite),
            )
        else:
            await message.answer(
                "🎉 Congratulations!\n\n"
                "✅ VIP Access Approved\n\n"
                "Couldn't auto-generate an invite link — please contact the "
                "admin so they can add you manually.",
                reply_markup=kb_verified(None),
            )
    else:
        await user.update_from_dict({
            "status": "pending",
            "pending_since": utcnow(),
        }).save()
        await _audit(
            user.telegram_id,
            "pending_activation",
            f"flags={snapshot.progress_flags} deposit_bucket={snapshot.deposit_bucket}",
        )
        poll = max(1, int(PENDING_POLL_MINUTES))
        giveup = max(1, int(PENDING_AUTO_GIVEUP_HOURS))
        deposit_line = (
            f"Make a deposit of at least ${int(MIN_DEPOSIT_USD)} on your "
            "Exness account."
            if MIN_DEPOSIT_USD > 10
            else "Make your first deposit on your Exness account."
        )
        if ACTIVATION_REQUIRE_TRADE:
            steps = f"1️⃣ {deposit_line}\n2️⃣ Place at least one trade.\n"
        else:
            steps = f"➡️ {deposit_line}\n"
        await message.answer(
            "🟡 Almost there!\n\n"
            "Your Exness account is connected under our partner, but it's "
            "not activated yet. To activate:\n\n"
            f"{steps}\n"
            f"We'll auto-check every ~{poll} minutes for the next {giveup} "
            "hours. After that, tap “Re-check now” whenever you're ready.",
            reply_markup=kb_pending_help(),
        )


# ---------------------------------------------------------------------------
# The Join-VIP funnel: start at the first missing piece.
# ---------------------------------------------------------------------------
async def _enter_funnel(user: User | None, message: Message,
                        state: FSMContext, bot: Bot,
                        *, force_uid: bool = False) -> None:
    """Move the user to the next required step (email → phone → UID), or
    re-run the check if everything is on file.

    `force_uid=True` jumps straight to the UID step regardless (used by
    the "I entered the wrong ID" button) as long as email + phone exist.
    """
    if user is None:
        await message.answer(EMAIL_PROMPT_TEXT, reply_markup=kb_cancel())
        await state.set_state(VerifyState.awaiting_email)
        return

    if not user.email:
        await message.answer(EMAIL_PROMPT_TEXT, reply_markup=kb_cancel())
        await state.set_state(VerifyState.awaiting_email)
        return

    if not user.phone:
        await message.answer(PHONE_PROMPT_TEXT, reply_markup=kb_phone_request())
        await state.set_state(VerifyState.awaiting_phone)
        return

    if force_uid or not user.exness_uid:
        if force_uid and user.exness_uid:
            await message.answer(
                f"✏️ Current Exness ID on file: {user.exness_uid}\n\n"
                + UID_PROMPT_TEXT,
                reply_markup=kb_cancel(),
            )
        else:
            await message.answer(UID_PROMPT_TEXT, reply_markup=kb_cancel())
        await state.set_state(VerifyState.awaiting_uid)
        return

    # Everything on file → just re-check.
    await state.clear()
    await message.answer(VERIFY_DELAY_TEXT)
    await _verify_and_route(user, message, bot)


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
ADMIN_PANEL_TEXT = (
    "🛠 Admin panel\n\n"
    "Quick reference (full list via /help):\n"
    "/stats — counts per status\n"
    "/user <telegram_id|email|UID> — user info\n"
    "/check <UID> — manual API check\n"
    "/recheck <telegram_id|email|UID> — force re-verification now\n"
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
            "VIP access is active. Need the invite link again? Tap below.",
            reply_markup=kb_verified(None),
        )
        return

    if user.status == "pending":
        need = (
            f"a deposit of at least ${int(MIN_DEPOSIT_USD)}"
            if MIN_DEPOSIT_USD > 10 else "your first deposit (any amount)"
        )
        if ACTIVATION_REQUIRE_TRADE:
            need += " plus at least one trade"
        await message.answer(
            "🟡 You're in the queue.\n\n"
            f"We're waiting for your account to activate ({need}). Once it "
            "does, we'll DM your invite link.",
            reply_markup=kb_pending_help(),
        )
        return

    # onboarding / warned / kicked → show the main menu.
    await message.answer(welcome_text(tg.first_name), reply_markup=kb_main_menu())


# ---------------------------------------------------------------------------
# Main-menu callbacks
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _safe_edit(
        callback, welcome_text(callback.from_user.first_name),
        reply_markup=kb_main_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "how_it_works")
async def cb_how_it_works(callback: CallbackQuery) -> None:
    await _safe_edit(callback, HOW_IT_WORKS_TEXT, reply_markup=kb_back_to_menu())
    await callback.answer()


@router.callback_query(F.data == "register_exness")
async def cb_register_exness(callback: CallbackQuery) -> None:
    await _safe_edit(callback, register_text(), reply_markup=kb_register_screen())
    await callback.answer()


@router.callback_query(F.data == "join_vip")
async def cb_join_vip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user = await User.filter(telegram_id=callback.from_user.id).first()
    if user and user.status == "verified":
        await _safe_edit(
            callback,
            "✅ You're already verified — VIP access is active.",
            reply_markup=kb_verified(None),
        )
        await callback.answer()
        return
    await _safe_edit(callback, JOIN_VIP_CHOICE_TEXT, reply_markup=kb_join_vip_choice())
    await callback.answer()


@router.callback_query(F.data == "acc_under")
async def cb_acc_under(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    user = await _ensure_user(callback.from_user)
    if user.status == "verified":
        await _safe_edit(
            callback, "✅ You're already verified — VIP access is active.",
            reply_markup=kb_verified(None),
        )
        await callback.answer()
        return
    await callback.answer()
    # The funnel sends fresh messages (FSM prompts), so just acknowledge
    # the callback and let _enter_funnel drive.
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _enter_funnel(user, callback.message, state, bot)


@router.callback_query(F.data == "acc_not_under")
async def cb_acc_not_under(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _safe_edit(callback, switch_partner_text(), reply_markup=kb_switch_partner())
    await callback.answer()


@router.callback_query(F.data == "create_new_exness")
async def cb_create_new_exness(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _safe_edit(
        callback, create_new_text(), reply_markup=kb_create_new(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "check_status")
async def cb_check_status(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user = await User.filter(telegram_id=callback.from_user.id).first()

    if not user or not user.exness_uid:
        await _safe_edit(
            callback,
            "📊 Account Verification\n\n"
            "We don't have an Exness ID on file for you yet. Tap “Join VIP "
            "for Free” to get started.",
            reply_markup=kb_status_no_uid(),
        )
        await callback.answer()
        return

    if user.status == "verified":
        await _safe_edit(
            callback,
            "✅ VIP Access Approved\n\n"
            "Your account is verified. Need the invite link again? Tap below.",
            reply_markup=kb_verified(None),
        )
        await callback.answer()
        return

    # pending / onboarding / warned / kicked → run a fresh check.
    await callback.answer("Checking…")
    try:
        await callback.message.edit_text(VERIFY_DELAY_TEXT)
    except Exception:
        await callback.message.answer(VERIFY_DELAY_TEXT)
    await _verify_and_route(user, callback.message, bot)


@router.callback_query(F.data == "recheck_pending")
async def cb_recheck_pending(callback: CallbackQuery, bot: Bot) -> None:
    user = await User.filter(telegram_id=callback.from_user.id).first()
    if not user or not user.exness_uid:
        await callback.answer("No Exness ID on file yet.", show_alert=True)
        return
    await callback.answer("Re-checking…")
    await _verify_and_route(user, callback.message, bot)


@router.callback_query(F.data == "edit_uid")
async def cb_edit_uid(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    user = await User.filter(telegram_id=callback.from_user.id).first()
    if not user:
        await _safe_edit(
            callback, welcome_text(callback.from_user.first_name),
            reply_markup=kb_main_menu(),
        )
        await callback.answer()
        return
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _enter_funnel(user, callback.message, state, bot, force_uid=True)


@router.callback_query(F.data == "new_invite")
async def cb_new_invite(callback: CallbackQuery, bot: Bot) -> None:
    user = await User.filter(telegram_id=callback.from_user.id).first()
    if not user or user.status != "verified":
        await callback.answer("Only verified members can get an invite link.", show_alert=True)
        return
    invite = await _generate_invite(bot, user.telegram_id)
    if invite:
        await callback.message.answer(
            "🔗 Here's a fresh invite link (single-use, expires in 24h):\n\n"
            f"{invite}",
            reply_markup=kb_verified(invite),
        )
        await callback.answer()
    else:
        await callback.answer("Couldn't generate a link — contact the admin.", show_alert=True)


@router.callback_query(F.data == "cancel_verify")
async def cb_cancel_verify(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await callback.message.answer("Cancelled.", reply_markup=ReplyKeyboardRemove())
    except Exception:
        pass
    await callback.message.answer(
        welcome_text(callback.from_user.first_name), reply_markup=kb_main_menu()
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM step 1 — email
# ---------------------------------------------------------------------------
@router.message(StateFilter(VerifyState.awaiting_email), F.text)
async def on_email_input(message: Message, state: FSMContext, bot: Bot) -> None:
    email = normalize_email(message.text)
    if not email:
        await message.answer(
            "That doesn't look like a valid email address.\n\n"
            "Please enter the email you used for your Exness account "
            "(e.g. name@example.com), or tap Cancel.",
            reply_markup=kb_cancel(),
        )
        return
    user = await _ensure_user(message.from_user)
    user.email = email
    await user.save()
    await message.answer("✅ Email saved.")
    # Move to the next missing step.
    await _enter_funnel(user, message, state, bot)


# ---------------------------------------------------------------------------
# FSM step 2 — phone
# ---------------------------------------------------------------------------
@router.message(StateFilter(VerifyState.awaiting_phone), F.contact)
async def on_phone_contact(message: Message, state: FSMContext, bot: Bot) -> None:
    contact = message.contact
    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer(
            "Please share your own phone number using the button below.",
            reply_markup=kb_phone_request(),
        )
        return
    user = await _ensure_user(message.from_user)
    user.phone = normalize_phone(contact.phone_number)
    await user.save()
    await message.answer("✅ Phone saved.", reply_markup=ReplyKeyboardRemove())
    await _enter_funnel(user, message, state, bot)


@router.message(StateFilter(VerifyState.awaiting_phone), F.text)
async def on_phone_text(message: Message, state: FSMContext, bot: Bot) -> None:
    phone = normalize_phone(message.text)
    if not phone or len(phone) < 8:
        await message.answer(
            "That doesn't look like a valid phone number.\n\n"
            "Please tap the “Share my phone” button below, or type the "
            "number in international format (e.g. +14155551234).",
            reply_markup=kb_phone_request(),
        )
        return
    user = await _ensure_user(message.from_user)
    user.phone = phone
    await user.save()
    await message.answer("✅ Phone saved.", reply_markup=ReplyKeyboardRemove())
    await _enter_funnel(user, message, state, bot)


# ---------------------------------------------------------------------------
# FSM step 3 — Exness ID (trading account number / UUID / hex prefix)
# ---------------------------------------------------------------------------
@router.message(StateFilter(VerifyState.awaiting_uid), F.text)
async def on_uid_input(message: Message, state: FSMContext, bot: Bot) -> None:
    raw = (message.text or "").strip()
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch == "-").strip("-")
    if not cleaned or len(cleaned) < 4:
        await message.answer(
            "That doesn't look like a valid Exness ID.\n\n"
            "Send your trading account number (8-9 digits, e.g. 12345678) "
            "or your full Client UUID. Try again, or tap Cancel.",
            reply_markup=kb_cancel(),
        )
        return
    uid = cleaned

    other = await User.filter(exness_uid=uid).exclude(telegram_id=message.from_user.id).first()
    if other:
        await message.answer(
            "⚠️ This Exness account is already linked to another Telegram "
            "user.\n\nIf this is your account, please contact the admin.",
            reply_markup=kb_back_to_menu(),
        )
        await state.clear()
        return

    user = await _ensure_user(message.from_user)
    user.exness_uid = uid
    await user.save()
    await state.clear()
    await message.answer(VERIFY_DELAY_TEXT)
    await _verify_and_route(user, message, bot)


# ---------------------------------------------------------------------------
# /help — users get the welcome screen; admin /help lives in handlers/admin.py.
# ---------------------------------------------------------------------------
@router.message(Command("help"), F.chat.type == "private", ~F.from_user.id.in_(ADMIN_IDS))
async def cmd_help(message: Message, state: FSMContext) -> None:
    await cmd_start(message, state)


# ---------------------------------------------------------------------------
# Backward-compat: old keyboards may still emit these callbacks.
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "start_verify")
async def cb_legacy_start_verify(callback: CallbackQuery, state: FSMContext) -> None:
    await cb_join_vip(callback, state)


@router.callback_query(F.data == "my_status")
async def cb_legacy_my_status(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await cb_check_status(callback, state, bot)

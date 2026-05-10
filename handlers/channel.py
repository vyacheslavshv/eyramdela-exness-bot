"""Channel-side events: chat_join_request and my_chat_member.

Channel admins can grant access manually too. We only auto-approve users
that are 'verified' in our DB. Everyone else is declined with a hint to
DM the bot.
"""

from aiogram import Bot, Router
from aiogram.types import ChatJoinRequest, ChatMemberUpdated
from loguru import logger

from config import ADMIN_IDS, CHANNEL_ID
from models import User

router = Router()


async def _safe(coro):
    try:
        await coro
    except Exception as e:
        logger.warning(f"channel action failed: {e}")


@router.chat_join_request()
async def on_join_request(event: ChatJoinRequest, bot: Bot) -> None:
    if CHANNEL_ID and event.chat.id != CHANNEL_ID:
        return

    tg_user = event.from_user
    if tg_user.is_bot or tg_user.id in ADMIN_IDS:
        await _safe(event.approve())
        return

    user = await User.filter(telegram_id=tg_user.id).first()
    if user and user.status == "verified":
        await _safe(event.approve())
        await User.filter(telegram_id=tg_user.id).update(
            username=tg_user.username, first_name=tg_user.first_name
        )
        logger.info(f"Approved channel join for verified user {tg_user.id}")
        return

    await _safe(event.decline())
    logger.info(
        f"Declined channel join for unverified user {tg_user.id} "
        f"(@{tg_user.username}) — status={user.status if user else 'no DB row'}"
    )

    # Best-effort nudge — only succeeds if they DM'd us before.
    try:
        await bot.send_message(
            tg_user.id,
            "👋 You can't join the VIP channel directly — "
            "please verify your Exness account here first.\n\n"
            "Send /start to begin.",
        )
    except Exception:
        pass


@router.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated, bot: Bot) -> None:
    """Telemetry only — log who joined/left so admin can audit."""
    if CHANNEL_ID and event.chat.id != CHANNEL_ID:
        return

    old = event.old_chat_member.status
    new = event.new_chat_member.status
    tg_user = event.new_chat_member.user
    if tg_user.is_bot:
        return

    if old in ("left", "kicked") and new in ("member", "restricted"):
        logger.info(f"Channel join: {tg_user.id} (@{tg_user.username})")
    elif new == "kicked":
        logger.info(f"Channel kick: {tg_user.id} (@{tg_user.username})")
    elif new == "left":
        logger.info(f"Channel left: {tg_user.id} (@{tg_user.username})")

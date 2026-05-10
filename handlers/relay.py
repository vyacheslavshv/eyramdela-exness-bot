"""User <-> admin DM relay.

Forwards a non-admin DM to every admin in ADMIN_IDS. Each forward writes
its own RelayMessage row (one per admin chat) so any admin can reply by
quoting the forwarded message in their chat — the lookup is by
forwarded_msg_id, which is unique per admin.
"""

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message
from loguru import logger

from config import ADMIN_IDS
from models import RelayMessage

router = Router()
router.message.filter(F.chat.type == "private")


@router.message(F.from_user.id.in_(ADMIN_IDS), F.reply_to_message)
async def admin_reply(message: Message, bot: Bot) -> None:
    relay = await RelayMessage.filter(
        forwarded_msg_id=message.reply_to_message.message_id
    ).first()
    if not relay:
        return
    try:
        await bot.copy_message(
            chat_id=relay.user_telegram_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception as e:
        await message.answer(f"Could not deliver message: {e}")
        logger.error(f"Relay delivery failed to {relay.user_telegram_id}: {e}")


@router.message(~F.from_user.id.in_(ADMIN_IDS), StateFilter(None))
async def user_dm(message: Message, bot: Bot) -> None:
    if not ADMIN_IDS:
        return
    for admin_id in ADMIN_IDS:
        try:
            forwarded = await message.forward(admin_id)
            await RelayMessage.create(
                forwarded_msg_id=forwarded.message_id,
                user_telegram_id=message.from_user.id,
            )
        except Exception as e:
            logger.error(
                f"Relay forward to admin {admin_id} failed "
                f"(from {message.from_user.id}): {e}"
            )

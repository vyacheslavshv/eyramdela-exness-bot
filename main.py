import asyncio
import os
import sys

from aiogram import Bot, Dispatcher
from loguru import logger

from config import BOT_TOKEN, CHANNEL_ID, TEST_MODE
from exness_api import self_test
from handlers import setup_routers
from scheduler import scheduler, start_scheduler
from utils import close_db, init_db, setup_logging


async def main() -> None:
    setup_logging(level="INFO")

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set in .env")
        sys.exit(1)
    if CHANNEL_ID == 0:
        logger.warning("CHANNEL_ID is 0 — channel actions will fail until set")

    os.makedirs("data", exist_ok=True)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(setup_routers())

    await init_db()

    if TEST_MODE:
        logger.warning("TEST_MODE is ON — Exness API calls are bypassed")
    else:
        ok = await self_test()
        if not ok:
            logger.warning(
                "Exness self-test failed at startup — verify EXNESS_LOGIN / "
                "EXNESS_PASSWORD. Bot will keep running and retry on demand."
            )

    start_scheduler(bot)
    logger.info("Bot started")

    try:
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "callback_query",
                "chat_member",
                "chat_join_request",
                "my_chat_member",
            ],
        )
    finally:
        scheduler.shutdown(wait=False)
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

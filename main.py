import asyncio

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from loguru import logger

from config import BOT_TOKEN
from utils import setup_logging, init_db, close_db

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Hello!")


async def main():
    setup_logging()
    await init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await close_db()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())

import os
import sys
import logging
from loguru import logger
from tortoise import Tortoise
from config import TORTOISE_ORM


def setup_logging(file_path="logs/bot.log", level="INFO"):
    logger.remove()
    log_dir = os.path.dirname(file_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    log_format = "<green>{time:MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"

    logger.add(sys.stderr, level=level, format=log_format)
    logger.add(file_path, level=level, format=log_format, rotation="10 MB", retention="7 days")

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


async def init_db():
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas()


async def close_db():
    await Tortoise.close_connections()

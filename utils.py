import logging
import os
import sys
import threading
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from tortoise import Tortoise

from config import DISPLAY_TZ, TORTOISE_ORM


# ---------------------------------------------------------------------------
# Logging — stderr + size-capped file sink
# ---------------------------------------------------------------------------
class _SingleFileSink:
    """Append-only sink that truncates from the head once max_bytes is hit."""

    def __init__(self, file_path: str, max_bytes: int, keep_bytes: int):
        self.file_path = file_path
        self.max_bytes = max_bytes
        self.keep_bytes = keep_bytes
        self.lock = threading.Lock()
        self._open()

    def _open(self):
        self.file = open(self.file_path, "a", encoding="utf-8")

    def _truncate_file(self):
        self.file.flush()
        with open(self.file_path, "rb") as reader:
            data = reader.read()
        if len(data) <= self.keep_bytes:
            return
        tail = data[-self.keep_bytes:]
        split = tail.find(b"\n")
        if split != -1:
            tail = tail[split + 1:]
        self.file.close()
        with open(self.file_path, "wb") as writer:
            writer.write(tail)
        self._open()

    def write(self, message):
        with self.lock:
            self.file.write(str(message))
            self.file.flush()
            if self.file.tell() >= self.max_bytes:
                self._truncate_file()

    def stop(self):
        with self.lock:
            self.file.close()


class _InterceptHandler(logging.Handler):
    """Route stdlib logging into loguru."""

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


def setup_logging(file_path: str = "logs/bot.log",
                  level: str = "INFO",
                  max_file_bytes: int = 50 * 1024 * 1024) -> None:
    logger.remove()
    log_dir = os.path.dirname(file_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    fmt = "<green>{time:MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    logger.add(sys.stderr, level=level, format=fmt)
    sink = _SingleFileSink(file_path, max_file_bytes, int(max_file_bytes * 0.8))
    logger.add(sink, level=level, format=fmt)

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for noisy in (
        "aiogram.event",
        "aiosqlite",
        "apscheduler.scheduler",
        "apscheduler.executors.default",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# DB init — generate_schemas + light forward-compat ALTERs
# ---------------------------------------------------------------------------
async def init_db() -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas(safe=True)

    conn = Tortoise.get_connection("default")
    # Defensive: if an older `users` table exists from a prior version,
    # try to add any new columns. Failing means the column already exists.
    extra_columns = [
        "email VARCHAR(255)",
        "phone VARCHAR(32)",
        "exness_uid VARCHAR(100)",
        "last_check_at TIMESTAMP",
        "last_warning_at TIMESTAMP",
        "kicked_at TIMESTAMP",
        "pending_since TIMESTAMP",
        "last_client_status VARCHAR(20)",
        "last_progress_flags TEXT",
        "last_deposit_total NUMERIC(14, 2)",
        "last_trade_at TIMESTAMP",
        "consecutive_api_errors INTEGER DEFAULT 0",
    ]
    for col in extra_columns:
        try:
            await conn.execute_query(f"ALTER TABLE users ADD COLUMN {col}")
        except Exception:
            pass


async def close_db() -> None:
    await Tortoise.close_connections()


# ---------------------------------------------------------------------------
# Time formatting helpers
# ---------------------------------------------------------------------------
def _display_zone():
    """Best-effort tz lookup; falls back to UTC if zoneinfo not available."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(DISPLAY_TZ)
    except Exception:
        return timezone.utc


def fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        local = dt.astimezone(_display_zone())
    except Exception:
        local = dt.astimezone(timezone.utc)
    suffix = local.strftime("%Z") or "UTC"
    return local.strftime(f"%Y-%m-%d %H:%M {suffix}")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Email validation (lightweight — we only sanity-check the shape)
# ---------------------------------------------------------------------------
import re as _re

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def normalize_email(raw: Optional[str]) -> Optional[str]:
    """Trim + lowercase + shape-check. Returns None if it doesn't look like
    an email at all."""
    if not raw:
        return None
    e = raw.strip().lower()
    if not e or len(e) > 255 or not _EMAIL_RE.match(e):
        return None
    return e


# ---------------------------------------------------------------------------
# Phone normalization (best-effort; works without phonenumbers too)
# ---------------------------------------------------------------------------
def normalize_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        import phonenumbers  # type: ignore

        # Telegram returns digits without "+" sometimes; try both.
        candidate = raw if raw.startswith("+") else f"+{raw}"
        parsed = phonenumbers.parse(candidate, None)
        if phonenumbers.is_possible_number(parsed):
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
    except Exception:
        pass

    digits = "".join(c for c in raw if c.isdigit())
    return f"+{digits}" if digits else None

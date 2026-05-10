import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "")
    if not raw:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _id_list(name: str) -> tuple[int, ...]:
    """Parse a comma- or semicolon-separated list of Telegram IDs."""
    raw = os.getenv(name, "")
    if not raw:
        return ()
    out: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except ValueError:
            continue
    return tuple(out)


# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ADMIN_IDS = comma-separated. ADMIN_ID kept as a single-value fallback for
# legacy .env files. The first admin in the resolved list is the "primary"
# one — DM relay forwards land there too if no other admin is reachable.
_admin_ids_csv = _id_list("ADMIN_IDS")
_admin_id_legacy = _int("ADMIN_ID", 0)
if _admin_ids_csv:
    ADMIN_IDS: frozenset[int] = frozenset(_admin_ids_csv)
elif _admin_id_legacy:
    ADMIN_IDS = frozenset({_admin_id_legacy})
else:
    ADMIN_IDS = frozenset()
PRIMARY_ADMIN_ID: int = next(iter(_admin_ids_csv or ((_admin_id_legacy,) if _admin_id_legacy else ())), 0)

CHANNEL_ID = _int("CHANNEL_ID", 0)
CHANNEL_INVITE_LINK = os.getenv("CHANNEL_INVITE_LINK", "")

# --- Exness Partnership API ---
EXNESS_BASE_URL = os.getenv("EXNESS_BASE_URL", "https://my.exnessaffiliates.com").rstrip("/")
EXNESS_LOGIN = os.getenv("EXNESS_LOGIN", "")
EXNESS_PASSWORD = os.getenv("EXNESS_PASSWORD", "")
EXNESS_REFERRAL_LINK = os.getenv("EXNESS_REFERRAL_LINK", "")
EXNESS_PARTNER_CODE = os.getenv("EXNESS_PARTNER_CODE", "")

# Customer-facing deep links into the Exness PA, shown to a user who has
# already registered and just needs to deposit / trade to activate.
EXNESS_DEPOSIT_URL = os.getenv(
    "EXNESS_DEPOSIT_URL",
    "https://my.exness.com/pa/payments-and-wallet/deposit",
)
EXNESS_PA_URL = os.getenv("EXNESS_PA_URL", "https://my.exness.com/pa/")

# --- Logic tuning ---
MIN_DEPOSIT_USD = _float("MIN_DEPOSIT_USD", 50.0)
INACTIVITY_WARN_DAYS = _int("INACTIVITY_WARN_DAYS", 11)
INACTIVITY_KICK_DAYS = _int("INACTIVITY_KICK_DAYS", 14)
RECHECK_INTERVAL_HOURS = _float("RECHECK_INTERVAL_HOURS", 6.0)
PENDING_POLL_MINUTES = _float("PENDING_POLL_MINUTES", 5.0)
PENDING_AUTO_GIVEUP_HOURS = _float("PENDING_AUTO_GIVEUP_HOURS", 24.0)
WARNING_GRACE_DAYS = _int("WARNING_GRACE_DAYS", 3)

BRAND_NAME = os.getenv("BRAND_NAME", "VIP Signals")

# --- Storage / runtime ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite://data/db.sqlite3")
TEST_MODE = _bool("TEST_MODE", False)
DISPLAY_TZ = os.getenv("DISPLAY_TZ", "UTC")


TORTOISE_ORM = {
    "connections": {"default": DATABASE_URL},
    "apps": {
        "models": {
            "models": ["models", "aerich.models"],
            "default_connection": "default",
        },
    },
}

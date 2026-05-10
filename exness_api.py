"""Async client for the Exness Affiliates API.

Auth: JWT obtained via POST /api/v2/auth/. Token TTL is ~6h. We cache the
token in memory and re-auth proactively (or on 401).

User-input UIDs are tricky:
* Some Exness users will paste their *trading account number* (8-9 digits).
* Others will paste a UUID-shaped client_uid.

The reports endpoints accept ``client_uid`` (UUID). Passing a numeric
trading account number to ``/api/v2/reports/clients/?client_uid=N`` makes
Exness return HTTP 500. So we resolve user input to a UUID first via the
accounts endpoint (which tolerates either format and returns a row that
also contains ``client_uid`` and ``client_account``).

Field reference (from the real OpenAPI schema, May 2026):

* ``/api/v2/reports/clients/`` row exposes:
    client_uid, client_status, partner_account, client_country,
    kyc_passed (bool), ftd_received (bool), ftt_made (bool),
    client_balance (int), client_equity (int),
    deposit_amount (int — total deposits in USD),
    ftd_amount (int — first time deposit amount in USD),
    trade_fn (last trade datetime), reg_date, …
* ``/api/reports/clients/accounts/`` row exposes:
    client_uid, client_account, client_account_type, platform,
    client_account_created, client_account_last_trade,
    volume_lots, volume_mln_usd, reward_usd, …

A few production accounts may emit the older ``contact_sharing_progress_status``
list shape (per the brief). We support both.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
from loguru import logger

from config import (
    EXNESS_BASE_URL,
    EXNESS_LOGIN,
    EXNESS_PASSWORD,
    MIN_DEPOSIT_USD,
    TEST_MODE,
)


TOKEN_TTL_SECONDS = 6 * 60 * 60
TOKEN_REFRESH_MARGIN = 5 * 60

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=20)

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass
class _TokenCache:
    token: Optional[str] = None
    issued_at: float = 0.0


_token = _TokenCache()
_token_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
async def _login() -> Optional[str]:
    if not EXNESS_LOGIN or not EXNESS_PASSWORD:
        logger.error("EXNESS_LOGIN / EXNESS_PASSWORD not configured")
        return None

    url = f"{EXNESS_BASE_URL}/api/v2/auth/"
    payload = {"login": EXNESS_LOGIN, "password": EXNESS_PASSWORD}

    try:
        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.post(url, json=payload) as resp:
                body = await resp.text()
                if resp.status != 200:
                    logger.error(f"Exness auth failed: {resp.status} {body[:300]}")
                    return None
                try:
                    data = json.loads(body)
                except Exception:
                    logger.error(f"Exness auth: bad JSON: {body[:300]}")
                    return None
                token = data.get("token")
                if not token:
                    logger.error(f"Exness auth: no token in response: {body[:300]}")
                    return None
                logger.info("Exness JWT obtained")
                return token
    except Exception as e:
        logger.error(f"Exness auth network error: {e}")
        return None


async def _get_token(force_refresh: bool = False) -> Optional[str]:
    async with _token_lock:
        now = time.time()
        if not force_refresh and _token.token and \
                now - _token.issued_at < TOKEN_TTL_SECONDS - TOKEN_REFRESH_MARGIN:
            return _token.token

        new_token = await _login()
        if new_token:
            _token.token = new_token
            _token.issued_at = now
            return new_token
        return None


async def force_reauth() -> bool:
    return (await _get_token(force_refresh=True)) is not None


# ---------------------------------------------------------------------------
# Generic GET
# ---------------------------------------------------------------------------
async def _api_get(path: str, params: Optional[dict] = None) -> Optional[Any]:
    """GET with auto re-auth on 401. Returns parsed JSON, or None on any error."""
    token = await _get_token()
    if not token:
        return None
    url = f"{EXNESS_BASE_URL}{path}"

    async def _do(tok: str) -> tuple[int, str]:
        headers = {
            "Authorization": f"JWT {tok}",
            "Accept": "application/json",
        }
        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.get(url, headers=headers, params=params) as resp:
                return resp.status, await resp.text()

    try:
        status, text = await _do(token)
        if status == 401:
            logger.warning(f"Exness 401 on {path} — re-auth and retry")
            token = await _get_token(force_refresh=True)
            if not token:
                return None
            status, text = await _do(token)

        if status != 200:
            logger.error(f"Exness {path} -> {status}: {text[:300]}")
            return None
        try:
            return json.loads(text)
        except Exception:
            logger.error(f"Exness {path}: bad JSON: {text[:300]}")
            return None
    except Exception as e:
        logger.error(f"Exness {path} network error: {e}")
        return None


# ---------------------------------------------------------------------------
# Public bot API
# ---------------------------------------------------------------------------
async def self_test() -> bool:
    if TEST_MODE:
        logger.info("TEST_MODE: Exness self-test bypassed")
        return True
    data = await _api_get("/api/partner/summary/")
    if data is None:
        logger.warning("Exness self-test FAILED")
        return False
    logger.info("Exness self-test OK")
    return True


def _is_uuid(s: str) -> bool:
    return bool(UUID_RE.match(s or ""))


# ---------------------------------------------------------------------------
# Resolve user input -> client_uid (UUID) via the accounts endpoint
# ---------------------------------------------------------------------------
async def _accounts_search(client_uid: str) -> Optional[list[dict]]:
    """Wrap the accounts endpoint. Returns list, or None on transient error."""
    data = await _api_get(
        "/api/reports/clients/accounts/", params={"client_uid": client_uid}
    )
    if data is None:
        return None
    if isinstance(data, dict):
        return data.get("data") or []
    if isinstance(data, list):
        return data
    return []


async def _accounts_full_scan() -> Optional[list[dict]]:
    """Last-resort full pull of all partner accounts."""
    data = await _api_get("/api/reports/clients/accounts/")
    if data is None:
        return None
    if isinstance(data, dict):
        return data.get("data") or []
    if isinstance(data, list):
        return data
    return []


async def resolve_client_uid(user_input: str) -> Optional[str | object]:
    """
    Try to map whatever the user pasted (UUID, account number, or even a
    concatenation) to a real client_uid (UUID).

    Returns:
      * str        — resolved UUID
      * the dict   — a special sentinel ``NOT_FOUND`` (see below) when the
                     API answered definitively "no such client"
      * None       — transient error
    """
    raw = (user_input or "").strip()
    if not raw:
        return NOT_FOUND

    # Already a UUID? Use it as-is.
    if _is_uuid(raw):
        return raw

    # Accounts endpoint accepts numeric inputs without 500'ing.
    accounts = await _accounts_search(raw)
    if accounts is None:
        return None  # transient
    for acc in accounts:
        cu = acc.get("client_uid")
        if cu:
            return cu

    # Fallback: scan all partner accounts and match on client_account.
    full = await _accounts_full_scan()
    if full is None:
        return None
    for acc in full:
        if str(acc.get("client_account") or "") == str(raw):
            cu = acc.get("client_uid")
            if cu:
                return cu

    return NOT_FOUND


class _NotFoundSentinel:
    def __repr__(self) -> str:
        return "<NOT_FOUND>"


NOT_FOUND = _NotFoundSentinel()


# ---------------------------------------------------------------------------
# Fetch a fully-typed client snapshot
# ---------------------------------------------------------------------------
@dataclass
class ClientSnapshot:
    under_partner: bool
    client_status: Optional[str]            # ACTIVE / INACTIVE / LEFT / CHANGING
    progress_flags: list[str]               # synthetic, e.g. ["ftt_made", "ftd_received"]
    deposit_total: float                    # USD
    balance: float                          # USD (live)
    last_trade_at: Optional[datetime]
    client_uid: Optional[str] = None        # resolved UUID
    raw: Optional[dict] = None              # raw client row (for /check debug)


def _coerce_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(v, str):
        s = v.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(v, fmt)
                    return dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
    return None


def _coerce_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _flags_from_record(rec: dict) -> list[str]:
    """Synthesize the brief's ``progress_flags`` list from real schema fields.

    Supports both shapes:
    * Modern: bool fields (kyc_passed, ftd_received, ftt_made) on the row.
    * Legacy: a ``contact_sharing_progress_status`` list with string flags.
    """
    out: list[str] = []
    if rec.get("kyc_passed"):
        out.append("kyc_passed")
    if rec.get("ftd_received"):
        out.append("ftd_received")
    if rec.get("ftt_made"):
        out.append("ftt_made")

    legacy = rec.get("contact_sharing_progress_status")
    if isinstance(legacy, list):
        for f in legacy:
            s = str(f)
            if s and s not in out:
                out.append(s)
    elif isinstance(legacy, str) and legacy and legacy not in out:
        out.append(legacy)
    return out


def _last_trade_from_record(rec: dict) -> Optional[datetime]:
    for key in ("trade_fn", "last_trade_at", "last_trade_date"):
        v = rec.get(key)
        if v:
            dt = _coerce_dt(v)
            if dt:
                return dt
    return None


async def _fetch_client_row(client_uid: str) -> Optional[dict]:
    """Return the row from /api/v2/reports/clients/ for this UUID."""
    data = await _api_get(
        "/api/v2/reports/clients/", params={"client_uid": client_uid}
    )
    if data is None:
        return None
    items = data.get("data") if isinstance(data, dict) else data
    if isinstance(items, list) and items:
        return items[0]
    return {}


async def fetch_client(uid: str) -> Optional[dict]:
    """
    Resolve user input to a UUID, then return the matching client row.

    * dict  — row exists (under partner)
    * `{}`  — definitively not under partner
    * None  — transient error
    """
    if TEST_MODE:
        logger.info(f"TEST_MODE: fake fetch_client uid={uid}")
        return {
            "client_uid": uid,
            "client_status": "ACTIVE",
            "kyc_passed": True,
            "ftd_received": True,
            "ftt_made": True,
            "deposit_amount": 100,
            "ftd_amount": 100,
            "client_balance": 100,
            "client_equity": 100,
            "trade_fn": datetime.now(timezone.utc).isoformat(),
        }

    resolved = await resolve_client_uid(uid)
    if resolved is None:
        return None
    if isinstance(resolved, _NotFoundSentinel):
        return {}
    row = await _fetch_client_row(resolved)
    if row is None:
        return None
    return row


async def fetch_accounts(uid: str) -> Optional[list[dict]]:
    """Return raw accounts list for /check debugging. Tolerant to any input."""
    if TEST_MODE:
        return [{
            "client_uid": uid,
            "client_account": "TEST",
            "client_account_last_trade": datetime.now(timezone.utc).isoformat(),
            "volume_lots": 0,
        }]
    accounts = await _accounts_search(uid)
    if accounts is not None and accounts:
        return accounts
    # Fallback if the input was a numeric trading account number
    if not _is_uuid(uid):
        full = await _accounts_full_scan()
        if full is None:
            return None
        return [a for a in full if str(a.get("client_account") or "") == str(uid)]
    return accounts or []


def summarize_accounts(accounts: list[dict]) -> dict:
    """Used by /check to report a normalized view alongside raw JSON."""
    last_trade: Optional[datetime] = None
    for acc in accounts or []:
        for k in ("client_account_last_trade", "last_trade_at", "last_trade_date"):
            v = acc.get(k)
            if v:
                dt = _coerce_dt(v)
                if dt and (last_trade is None or dt > last_trade):
                    last_trade = dt
    return {
        "deposit_total": 0.0,   # accounts endpoint doesn't expose this in 2026 schema
        "balance": 0.0,
        "last_trade_at": last_trade,
    }


async def fetch_snapshot(uid: str) -> Optional[ClientSnapshot]:
    row = await fetch_client(uid)
    if row is None:
        return None
    if row == {}:
        return ClientSnapshot(
            under_partner=False,
            client_status=None,
            progress_flags=[],
            deposit_total=0.0,
            balance=0.0,
            last_trade_at=None,
            client_uid=None,
            raw=None,
        )

    deposit_total = _coerce_float(
        row.get("deposit_amount")
        or row.get("ftd_amount")
        or 0
    )
    balance = _coerce_float(
        row.get("client_balance")
        if row.get("client_balance") is not None
        else row.get("client_equity")
    )
    last_trade = _last_trade_from_record(row)

    return ClientSnapshot(
        under_partner=True,
        client_status=row.get("client_status"),
        progress_flags=_flags_from_record(row),
        deposit_total=deposit_total,
        balance=balance,
        last_trade_at=last_trade,
        client_uid=row.get("client_uid"),
        raw=row,
    )


# ---------------------------------------------------------------------------
# Activation gate
# ---------------------------------------------------------------------------
def is_activated(progress_flags: list[str], deposit_total_usd: float) -> bool:
    """Either ``ftt_made`` OR (``ftd_received`` AND deposit ≥ MIN)."""
    flags = set(progress_flags or [])
    has_first_trade = "ftt_made" in flags
    has_qualifying_deposit = (
        "ftd_received" in flags and (deposit_total_usd or 0) >= MIN_DEPOSIT_USD
    )
    return has_first_trade or has_qualifying_deposit

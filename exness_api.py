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
    ACTIVATION_REQUIRE_TRADE,
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


# A partner can have thousands of clients (one production partner has
# 2.6k+). The full /api/v2/reports/clients/ scan is ~N/200 HTTP calls and
# holds the whole list in memory — doing it per pending-user every poll
# cycle is what hammered a small VPS. Cache the scan result and reuse it.
_CLIENTS_CACHE_TTL = 600.0   # seconds
_clients_cache: dict = {"data": None, "ts": 0.0}
_clients_lock = asyncio.Lock()


async def _clients_paginated(max_pages: int = 60, page_size: int = 200,
                             *, force: bool = False) -> Optional[list[dict]]:
    """Page through /api/v2/reports/clients/ and return every row.

    Cached for ``_CLIENTS_CACHE_TTL`` seconds — the client list changes
    slowly, and a burst of UID resolutions (or the pending-poll job)
    must not trigger a fresh multi-page scan each time.

    The Exness API truncates ``client_uid`` to 8 hex chars in the
    ``/accounts/`` endpoint but returns the full 36-char UUID here, so
    this scan is how we upgrade a short id / numeric trading account to
    the canonical UUID.
    """
    async with _clients_lock:
        now = time.time()
        if not force and _clients_cache["data"] is not None and \
                now - _clients_cache["ts"] < _CLIENTS_CACHE_TTL:
            return _clients_cache["data"]

        out: list[dict] = []
        for page in range(max_pages):
            offset = page * page_size
            data = await _api_get(
                "/api/v2/reports/clients/",
                params={"limit": page_size, "offset": offset},
            )
            if data is None:
                # On a transient error, fall back to the (possibly stale)
                # cache rather than returning None and breaking lookups.
                return _clients_cache["data"]
            items = (
                data.get("data")
                if isinstance(data, dict)
                else (data if isinstance(data, list) else [])
            )
            if not items:
                break
            out.extend(items)
            totals = data.get("totals") if isinstance(data, dict) else {}
            avail = (totals or {}).get("available_for_request") or 0
            if len(out) >= avail > 0:
                break
            if len(items) < page_size:
                break

        _clients_cache["data"] = out
        _clients_cache["ts"] = now
        return out


# ---------------------------------------------------------------------------
# Deposit / balance "range ID" buckets (Exness reports these as a tier, not
# a dollar figure):  1: $0–10  2: $10–50  3: $50–250  4: $250–1000
#                    5: $1000–5000  6: >$5000   (0 / missing → unknown)
# ---------------------------------------------------------------------------
_BUCKET_LABELS = {
    0: "—",
    1: "$0–10",
    2: "$10–50",
    3: "$50–250",
    4: "$250–1000",
    5: "$1000–5000",
    6: ">$5000",
}


def bucket_label(b) -> str:
    try:
        return _BUCKET_LABELS.get(int(b or 0), str(b))
    except (TypeError, ValueError):
        return "—"


def min_deposit_bucket(min_usd: float) -> int:
    """Smallest deposit range-ID that *guarantees* the deposit is ≥ min_usd.

    ``min_usd <= 0`` → 1 (any account; combine with the ftd_received flag
    to mean "made some deposit"). Otherwise map to the bucket whose lower
    bound covers the threshold.
    """
    if min_usd <= 0:
        return 1
    if min_usd <= 10:
        return 2
    if min_usd <= 50:
        return 3
    if min_usd <= 250:
        return 4
    if min_usd <= 1000:
        return 5
    return 6


async def _short_uid_from_account_number(raw_digits: str) -> Optional[str | object]:
    """Map a numeric trading account number to the (truncated) client_uid
    via the /accounts/ endpoint's ``client_account`` filter.

    Returns:
      * str       — short hex client_uid (e.g. "bcd562bb")
      * NOT_FOUND — no such trading account under this partner
      * None      — transient error
    """
    data = await _api_get(
        "/api/reports/clients/accounts/", params={"client_account": raw_digits}
    )
    if data is None:
        return None
    items = (
        data.get("data")
        if isinstance(data, dict)
        else (data if isinstance(data, list) else [])
    )
    for acc in items:
        if str(acc.get("client_account") or "") == raw_digits:
            cu = (acc.get("client_uid") or "").lower()
            if cu:
                return cu
    return NOT_FOUND


async def resolve_client_uid(user_input: str) -> Optional[str | object]:
    """Map a user-typed identifier to the canonical full UUID.

    Accepts:
      * Full UUID  (bcd562bb-1bed-49d4-b63e-b4354657dba5) → returned as-is.
      * Hex prefix (bcd562bb, ≥6 hex chars) → upgraded via /clients/ scan.
      * Trading account number (250324410, digits) → resolved via
        /accounts/ then upgraded via /clients/ scan.

    Returns:
      * str         — full UUID
      * NOT_FOUND   — definitive miss
      * None        — transient API error
    """
    raw = (user_input or "").strip()
    if not raw:
        return NOT_FOUND

    if _is_uuid(raw):
        return raw.lower()

    raw_lc = raw.lower()
    is_hex = all(c in "0123456789abcdef" for c in raw_lc)

    short_uid: Optional[str] = None
    if raw.isdigit():
        # Trading account number flow.
        result = await _short_uid_from_account_number(raw)
        if result is None:
            return None
        if isinstance(result, _NotFoundSentinel):
            return NOT_FOUND
        short_uid = result
    elif is_hex and len(raw_lc) >= 6:
        short_uid = raw_lc
    else:
        return NOT_FOUND

    # Upgrade short uid → full UUID via /clients/ scan.
    full_clients = await _clients_paginated()
    if full_clients is None:
        return None

    matches: set[str] = set()
    for c in full_clients:
        cu = c.get("client_uid") or ""
        if cu.lower().startswith(short_uid):
            matches.add(cu)

    if len(matches) == 1:
        return next(iter(matches))
    if len(matches) > 1:
        logger.warning(
            f"resolve_client_uid: ambiguous prefix '{short_uid}' matched "
            f"{len(matches)} clients"
        )
        return NOT_FOUND
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
    # Exness reports money as a range-ID (1: $0–10 … 6: >$5000), not a
    # dollar figure. 0 = unknown/missing.
    deposit_bucket: int                     # total deposits range-ID
    ftd_bucket: int                         # first-time-deposit range-ID
    balance_bucket: int                     # current balance range-ID
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
    return {"last_trade_at": last_trade}


def _bucket(v) -> int:
    """Coerce a deposit/balance range-ID to an int in 0..6."""
    try:
        b = int(float(v))
    except (TypeError, ValueError):
        return 0
    return max(0, min(6, b))


async def fetch_snapshot(uid: str) -> Optional[ClientSnapshot]:
    row = await fetch_client(uid)
    if row is None:
        return None
    if row == {}:
        return ClientSnapshot(
            under_partner=False,
            client_status=None,
            progress_flags=[],
            deposit_bucket=0,
            ftd_bucket=0,
            balance_bucket=0,
            last_trade_at=None,
            client_uid=None,
            raw=None,
        )

    progress_flags = _flags_from_record(row)
    deposit_bucket = _bucket(row.get("deposit_amount"))
    ftd_bucket = _bucket(row.get("ftd_amount"))
    balance_bucket = _bucket(
        row.get("client_balance") if row.get("client_balance") is not None
        else row.get("client_equity")
    )
    last_trade = _last_trade_from_record(row)

    return ClientSnapshot(
        under_partner=True,
        client_status=row.get("client_status"),
        progress_flags=progress_flags,
        deposit_bucket=deposit_bucket,
        ftd_bucket=ftd_bucket,
        balance_bucket=balance_bucket,
        last_trade_at=last_trade,
        client_uid=row.get("client_uid"),
        raw=row,
    )


# ---------------------------------------------------------------------------
# Activation gate
# ---------------------------------------------------------------------------
def is_activated(progress_flags: list[str], deposit_bucket: int,
                 *, require_trade: bool | None = None) -> bool:
    """Activation = the client has made a real deposit, in a tier at or
    above what MIN_DEPOSIT_USD requires.

    Exness reports deposits as a *range-ID* (1: $0–10 … 6: >$5000), not an
    exact dollar figure, so a precise "$X minimum" can't be enforced — we
    map MIN_DEPOSIT_USD to the lowest range-ID that guarantees it (see
    ``min_deposit_bucket``). `MIN_DEPOSIT_USD=0` means "any deposit".

    ``ftd_received`` (real money came in — a no-deposit bonus trade does
    NOT set it) is always required. If ACTIVATION_REQUIRE_TRADE is on, a
    first trade is also required.
    """
    if require_trade is None:
        require_trade = ACTIVATION_REQUIRE_TRADE
    flags = set(progress_flags or [])
    if "ftd_received" not in flags:
        return False
    if (deposit_bucket or 0) < min_deposit_bucket(MIN_DEPOSIT_USD):
        return False
    if require_trade:
        return "ftt_made" in flags
    return True

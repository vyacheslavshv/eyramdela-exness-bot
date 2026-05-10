from tortoise import fields
from tortoise.models import Model


class User(Model):
    """A Telegram user that has interacted with the bot."""

    id = fields.IntField(pk=True)
    telegram_id = fields.BigIntField(unique=True, index=True)
    username = fields.CharField(max_length=255, null=True)
    first_name = fields.CharField(max_length=255, null=True)
    phone = fields.CharField(max_length=32, null=True)            # E.164
    exness_uid = fields.CharField(max_length=100, null=True, unique=True, index=True)

    # onboarding | pending | verified | warned | kicked
    status = fields.CharField(max_length=24, default="onboarding", index=True)

    started_at = fields.DatetimeField(auto_now_add=True)
    verified_at = fields.DatetimeField(null=True)
    last_check_at = fields.DatetimeField(null=True)
    last_warning_at = fields.DatetimeField(null=True)
    kicked_at = fields.DatetimeField(null=True)
    pending_since = fields.DatetimeField(null=True)     # set on entering "pending"; scheduler uses this to time out idle users

    last_client_status = fields.CharField(max_length=20, null=True)
    last_progress_flags = fields.TextField(null=True)             # JSON list
    last_deposit_total = fields.DecimalField(
        max_digits=14, decimal_places=2, null=True
    )
    last_trade_at = fields.DatetimeField(null=True)

    consecutive_api_errors = fields.IntField(default=0)

    class Meta:
        table = "users"


class RelayMessage(Model):
    """Maps a forwarded admin-side message back to the originating user."""

    id = fields.IntField(pk=True)
    forwarded_msg_id = fields.BigIntField(index=True)
    user_telegram_id = fields.BigIntField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "relay_messages"


class AuditLog(Model):
    """Append-only state-transition log for debugging + admin inspection."""

    id = fields.IntField(pk=True)
    telegram_id = fields.BigIntField(index=True)
    event = fields.CharField(max_length=64, index=True)
    detail = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)

    class Meta:
        table = "audit_log"

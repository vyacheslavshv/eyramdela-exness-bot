from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "audit_log" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "telegram_id" BIGINT NOT NULL,
    "event" VARCHAR(64) NOT NULL,
    "detail" TEXT,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) /* Append-only state-transition log for debugging + admin inspection. */;
CREATE INDEX IF NOT EXISTS "idx_audit_log_telegra_f60d35" ON "audit_log" ("telegram_id");
CREATE INDEX IF NOT EXISTS "idx_audit_log_event_cc5832" ON "audit_log" ("event");
CREATE INDEX IF NOT EXISTS "idx_audit_log_created_277f5d" ON "audit_log" ("created_at");
CREATE TABLE IF NOT EXISTS "relay_messages" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "forwarded_msg_id" BIGINT NOT NULL,
    "user_telegram_id" BIGINT NOT NULL,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) /* Maps a forwarded admin-side message back to the originating user. */;
CREATE INDEX IF NOT EXISTS "idx_relay_messa_forward_71a3a1" ON "relay_messages" ("forwarded_msg_id");
CREATE TABLE IF NOT EXISTS "users" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "telegram_id" BIGINT NOT NULL UNIQUE,
    "username" VARCHAR(255),
    "first_name" VARCHAR(255),
    "phone" VARCHAR(32),
    "exness_uid" VARCHAR(100) UNIQUE,
    "status" VARCHAR(24) NOT NULL DEFAULT 'onboarding',
    "started_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "verified_at" TIMESTAMP,
    "last_check_at" TIMESTAMP,
    "last_warning_at" TIMESTAMP,
    "kicked_at" TIMESTAMP,
    "last_client_status" VARCHAR(20),
    "last_progress_flags" TEXT,
    "last_deposit_total" VARCHAR(40),
    "last_trade_at" TIMESTAMP,
    "consecutive_api_errors" INT NOT NULL DEFAULT 0
) /* A Telegram user that has interacted with the bot. */;
CREATE INDEX IF NOT EXISTS "idx_users_telegra_ab91e9" ON "users" ("telegram_id");
CREATE INDEX IF NOT EXISTS "idx_users_exness__8dd260" ON "users" ("exness_uid");
CREATE INDEX IF NOT EXISTS "idx_users_status_941fc1" ON "users" ("status");
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSON NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "eJztmllv2zgQgP8K4acsNgkS2Tl235xj2yziZJG626JFIdAiLROWSJWkcqDIf1+SkqxbtV"
    "3bsbF6szkzFPkNxRkO9aPjM4Q9cdgPEZG3zO38CX50KPSx+lGS7YMODIJUohskHHlGGWot"
    "24vVRkJy6EglGENPYNWEsHA4CSRhVKv3gwBTdMCo9wKEhBIfKAMqiJYD1QsYMw4QHoWuS6"
    "gLfgcQ+YQCQkWAHa10qJ+DmKMepBRW12VIyfcQ25K5WE4wVx1//aaaCUX4GYvkbzC1xwR7"
    "KMeLIN2BabflS2Dabqj8yyjq0Y5sh3mhT1Pl4EVOGJ1pEyp1q4sp5moCunvJQ42Php4Xo0"
    "6IRiNNVaIhZmwQHsPQ007Q1iUfJI0ZhnGTw6j2nxqNMBN09VMOrOPeWe+8e9o7VypmJLOW"
    "s9doeuncI0ND4G7YeTVyKGGkYTCm3CT2sMuhb1cBvCBuLcOC4c9hJuiaaCYN68b5h2V1u2"
    "fWUff0/KR3dnZyfjTjWhY1Ab64eacZKwWm3rnobUygp5DxI4545PFeTiCvhjszKGBVU9lO"
    "rD58tj1MXTlRf097DcT+7T9cvu8/7J32fstju4sllhHlASIsIfHKBIf4uWZ5phZLIYz5NB"
    "BM99bVIGxANrz+bJaYL8R3L4tqb9D/bCj6L7Hk9v7uXaKeQXt5e39RQOpwrKdvw4qFeaUk"
    "kvi4Gm3esoAXxaaHyY/tXK9qCuheBau46yb4N4PrD8P+4J+cB676w2stsXL0k9a908Lann"
    "UCPt0M3wP9F3y5v7s2AJmQLjdPTPWGXzp6TDCUzKbsyYYoQyFpTUi96qg4nmb2d90wgs70"
    "CXJklyTMYnW6ZZFv+cUWSKFrvKLh6mHGycoD9uDLAAsBzS5bSmZy8saEhmtN249UxXxZzQ"
    "AGAkCdaOiZYBSlGAeCIAzinoCeJ5AMqOwCME5ULgKlzkdCgXk5qVlJj21Os/GcZuYw2xfu"
    "wolNlXWb3TRkN3qp20vnkVXW68K96pj9Nrx3K3KvnHkbutcQuj8KE5pKIdu0N4Zq/f7OGa"
    "H7YBi/5yY8qpgJJZhAAZRvsTZVIfaJyIkJpiMmK8oMy/TQRuD/eVVhQzTfIOya3yXA9XWF"
    "rM2OnIvzpQXr5GSO2oLSqi0uGFme5JhwIe1FWeatWpoJzUBxWAjkzGAnGXatORB2rVqCWl"
    "SoFj5Tdbi0w6q9s6FkmLNaCcq175s5kMdHR3OQVFq1KI0sz1LfRYRiEY6pxcZqrx1GR0yl"
    "cJrVyl7teWqwVn0N1irVYBUYvtyxI2/ZHju24NiRdewj5kTNYxnPFkxX4NrtKrxvkSeTaT"
    "e60oMqJXEm2Jku4cyScevObXCnOtxTNeFlHZo3b136xi6dEme61FabM2zduA1vpuMRTKW9"
    "eI5Zbb2Txx9rnqTdqs/ZrVLKbuAEnGl3CXvsQbeCbf3Ff435jsDd9FcAhhbC6vUg0pZMwo"
    "qPLK6wQ3zoNeAudVDcn6IeDuOedo381fXlzaB/u3fc24/O8QozkTi7wnvVy1j1j/CykTtr"
    "3G74b7zh66lhJ5TkUbkkIDbmnPGKjam2sl3fweZuO49+YddfwY3Bltx19dWh1Zl0qr62jS"
    "T7jd/apjo/u/Cqh9teSW38SuoRc6GHtECaljFZVy1wB+v7+tVYAGKsvpsA11KTVk+Uld8D"
    "//3h/q42eMjqL4I/UjXBr4g4ch94RMhv24m1gaKedXNeW0xhC+Fdd3Dx1uHl9T99Z+5d"
)

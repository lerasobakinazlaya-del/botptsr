import aiosqlite


class Database:
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path
        self.connection = None

    async def connect(self):
        self.connection = await aiosqlite.connect(self.db_path)
        await self._configure()
        await self.create_tables()

    async def _configure(self):
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA synchronous=NORMAL")
        await self.connection.execute("PRAGMA foreign_keys=ON")
        await self.connection.execute("PRAGMA busy_timeout=5000")
        await self.connection.commit()

    async def create_tables(self):
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                text TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                external_payment_id TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'RUB',
                status TEXT NOT NULL,
                is_first_payment INTEGER NOT NULL DEFAULT 0,
                paid_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT NULL,
                UNIQUE(provider, external_payment_id)
            )
            """
        )
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_user_id INTEGER NOT NULL,
                referred_user_id INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                reward_amount_minor_units INTEGER NOT NULL DEFAULT 0,
                external_payment_id TEXT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                converted_at TIMESTAMP NULL,
                rewarded_at TIMESTAMP NULL
            )
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_user_id_id
            ON messages (user_id, id DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_user_id_created_at
            ON messages (user_id, created_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_payments_user_id_paid_at
            ON payments (user_id, paid_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_payments_status_paid_at
            ON payments (status, paid_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_referrals_referrer_status
            ON referrals (referrer_user_id, status, created_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_referrals_referred_status
            ON referrals (referred_user_id, status, created_at DESC)
            """
        )
        await self.connection.commit()

    async def close(self):
        if self.connection is not None:
            await self.connection.close()

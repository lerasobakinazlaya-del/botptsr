from typing import Any


class ReferralService:
    def __init__(self, db, user_service, settings_service, state_repository=None):
        self.db = db
        self.user_service = user_service
        self.settings_service = settings_service
        self.state_repository = state_repository

    def get_settings(self) -> dict[str, Any]:
        return self.settings_service.get_runtime_settings()["referral"]

    async def register_referral(self, referrer_user_id: int, referred_user_id: int) -> bool:
        settings = self.get_settings()
        if not settings["enabled"]:
            return False

        if referrer_user_id <= 0 or referred_user_id <= 0:
            return False

        if not settings["allow_self_referral"] and referrer_user_id == referred_user_id:
            return False

        referrer_exists = await self.user_service.user_exists(referrer_user_id)
        if not referrer_exists:
            return False

        await self.db.connection.execute(
            """
            INSERT OR IGNORE INTO referrals (
                referrer_user_id,
                referred_user_id,
                status,
                reward_amount_minor_units
            )
            VALUES (?, ?, 'pending', 0)
            """,
            (referrer_user_id, referred_user_id),
        )
        await self.db.connection.commit()

        cursor = await self.db.connection.execute(
            """
            SELECT 1
            FROM referrals
            WHERE referrer_user_id = ? AND referred_user_id = ?
            """,
            (referrer_user_id, referred_user_id),
        )
        return await cursor.fetchone() is not None

    async def process_successful_payment(
        self,
        referred_user_id: int,
        amount_minor_units: int,
        external_payment_id: str,
        is_first_payment: bool,
    ) -> dict[str, Any] | None:
        settings = self.get_settings()
        if not settings["enabled"]:
            return None
        if settings["require_first_paid_invoice"] and not is_first_payment:
            return None

        cursor = await self.db.connection.execute(
            """
            SELECT referrer_user_id, status
            FROM referrals
            WHERE referred_user_id = ?
            LIMIT 1
            """,
            (referred_user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        referrer_user_id = int(row[0])
        current_status = str(row[1])
        if current_status == "rewarded":
            return None

        await self.db.connection.execute(
            """
            UPDATE referrals
            SET status = 'converted',
                reward_amount_minor_units = ?,
                external_payment_id = ?,
                converted_at = CURRENT_TIMESTAMP,
                rewarded_at = CASE WHEN rewarded_at IS NOT NULL THEN rewarded_at ELSE NULL END
            WHERE referred_user_id = ?
            """,
            (amount_minor_units, external_payment_id, referred_user_id),
        )
        await self.db.connection.commit()

        reward_result = await self._finalize_reward_if_ready(
            referrer_user_id=referrer_user_id,
            referred_user_id=referred_user_id,
            amount_minor_units=amount_minor_units,
            external_payment_id=external_payment_id,
        )
        if reward_result is not None:
            return reward_result

        reward_days = max(0, int(settings.get("reward_premium_days", 0)))
        reward_plan_key = str(settings.get("reward_plan_key") or "pro").strip().lower() or "pro"
        return {
            "referrer_user_id": referrer_user_id,
            "referred_user_id": referred_user_id,
            "reward_amount_minor_units": amount_minor_units,
            "reward_premium_days": reward_days,
            "reward_plan_key": reward_plan_key,
            "awarded_referrer_premium": bool(settings["award_referrer_premium"]),
            "awarded_referred_user_premium": bool(settings["award_referred_user_premium"]),
            "reward_granted": False,
        }

    async def process_activation(self, referred_user_id: int) -> dict[str, Any] | None:
        cursor = await self.db.connection.execute(
            """
            SELECT referrer_user_id, reward_amount_minor_units, external_payment_id, status
            FROM referrals
            WHERE referred_user_id = ?
            LIMIT 1
            """,
            (referred_user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        if str(row[3] or "") == "rewarded":
            return None
        return await self._finalize_reward_if_ready(
            referrer_user_id=int(row[0]),
            referred_user_id=referred_user_id,
            amount_minor_units=int(row[1] or 0),
            external_payment_id=str(row[2] or ""),
        )

    async def _finalize_reward_if_ready(
        self,
        *,
        referrer_user_id: int,
        referred_user_id: int,
        amount_minor_units: int,
        external_payment_id: str,
    ) -> dict[str, Any] | None:
        settings = self.get_settings()
        if settings.get("require_activation_before_reward", True) and not await self._is_activation_ready(referred_user_id):
            return None

        reward_days = max(0, int(settings.get("reward_premium_days", 0)))
        reward_plan_key = str(settings.get("reward_plan_key") or "pro").strip().lower() or "pro"
        if settings["award_referrer_premium"]:
            if reward_days > 0:
                await self.user_service.grant_subscription_days(referrer_user_id, reward_plan_key, reward_days)
        if settings["award_referred_user_premium"]:
            if reward_days > 0:
                await self.user_service.grant_subscription_days(referred_user_id, reward_plan_key, reward_days)

        await self.db.connection.execute(
            """
            UPDATE referrals
            SET status = 'rewarded',
                rewarded_at = CURRENT_TIMESTAMP
            WHERE referred_user_id = ?
            """,
            (referred_user_id,),
        )
        await self.db.connection.commit()

        return {
            "referrer_user_id": referrer_user_id,
            "referred_user_id": referred_user_id,
            "reward_amount_minor_units": amount_minor_units,
            "reward_premium_days": reward_days,
            "reward_plan_key": reward_plan_key,
            "awarded_referrer_premium": bool(settings["award_referrer_premium"]),
            "awarded_referred_user_premium": bool(settings["award_referred_user_premium"]),
            "reward_granted": True,
        }

    async def _is_activation_ready(self, referred_user_id: int) -> bool:
        if self.state_repository is None:
            return True
        state = await self.state_repository.get(referred_user_id)
        onboarding = dict((state or {}).get("onboarding") or {})
        return bool(str(onboarding.get("activation_reached_at") or "").strip())

    async def get_overview(self) -> dict[str, Any]:
        total_cursor = await self.db.connection.execute("SELECT COUNT(*) FROM referrals")
        total_row = await total_cursor.fetchone()

        converted_cursor = await self.db.connection.execute(
            "SELECT COUNT(*) FROM referrals WHERE status IN ('converted', 'rewarded')"
        )
        converted_row = await converted_cursor.fetchone()

        paid_cursor = await self.db.connection.execute(
            """
            SELECT COALESCE(SUM(reward_amount_minor_units), 0)
            FROM referrals
            WHERE status IN ('converted', 'rewarded')
            """
        )
        paid_row = await paid_cursor.fetchone()

        recent_cursor = await self.db.connection.execute(
            """
            SELECT referrer_user_id, referred_user_id, status, reward_amount_minor_units, created_at, converted_at
            FROM referrals
            ORDER BY COALESCE(converted_at, created_at) DESC, id DESC
            LIMIT 20
            """
        )
        recent_rows = await recent_cursor.fetchall()

        return {
            "total": total_row[0] if total_row else 0,
            "converted": converted_row[0] if converted_row else 0,
            "converted_amount_minor_units": int(paid_row[0] if paid_row else 0),
            "recent": [
                {
                    "referrer_user_id": row[0],
                    "referred_user_id": row[1],
                    "status": row[2],
                    "reward_amount_minor_units": row[3],
                    "created_at": row[4],
                    "converted_at": row[5],
                }
                for row in recent_rows
            ],
        }

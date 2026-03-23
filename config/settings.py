from dataclasses import dataclass
import os
from typing import List

from dotenv import load_dotenv


load_dotenv()


def parse_admin_ids(raw: str) -> List[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_int(raw: str | None, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    return int(raw)


@dataclass
class Settings:
    bot_token: str
    openai_api_key: str
    owner_id: int
    admin_id: List[int]
    redis_url: str
    debug: bool
    ai_log_full_prompt: bool
    ai_debug_prompt_user_id: int | None
    openai_max_parallel_requests: int
    openai_queue_size: int
    admin_dashboard_host: str
    admin_dashboard_port: int
    admin_dashboard_username: str
    admin_dashboard_password: str
    admin_dashboard_cache_ttl: int
    payment_provider_token: str
    payment_currency: str
    premium_price_minor_units: int
    premium_product_title: str
    premium_product_description: str


def get_settings() -> Settings:
    bot_token = os.getenv("BOT_TOKEN")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    owner_id = os.getenv("OWNER_ID")
    admin_id = os.getenv("ADMIN_ID")

    if not bot_token:
        raise ValueError("BOT_TOKEN not set in .env")

    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY not set in .env")

    if not owner_id:
        raise ValueError("OWNER_ID not set in .env")

    if not admin_id:
        raise ValueError("ADMIN_ID not set in .env")

    return Settings(
        bot_token=bot_token,
        openai_api_key=openai_api_key,
        owner_id=int(owner_id),
        admin_id=parse_admin_ids(admin_id),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        debug=parse_bool(os.getenv("DEBUG"), default=False),
        ai_log_full_prompt=parse_bool(
            os.getenv("AI_LOG_FULL_PROMPT"),
            default=False,
        ),
        ai_debug_prompt_user_id=parse_int(
            os.getenv("AI_DEBUG_PROMPT_USER_ID"),
            default=0,
        ) or None,
        openai_max_parallel_requests=parse_int(
            os.getenv("OPENAI_MAX_PARALLEL_REQUESTS"),
            default=4,
        ),
        openai_queue_size=parse_int(
            os.getenv("OPENAI_QUEUE_SIZE"),
            default=100,
        ),
        admin_dashboard_host=os.getenv("ADMIN_DASHBOARD_HOST", "127.0.0.1"),
        admin_dashboard_port=parse_int(
            os.getenv("ADMIN_DASHBOARD_PORT"),
            default=8080,
        ),
        admin_dashboard_username=os.getenv("ADMIN_DASHBOARD_USERNAME", "admin"),
        admin_dashboard_password=os.getenv("ADMIN_DASHBOARD_PASSWORD", "change-me"),
        admin_dashboard_cache_ttl=parse_int(
            os.getenv("ADMIN_DASHBOARD_CACHE_TTL"),
            default=15,
        ),
        payment_provider_token=os.getenv("PAYMENT_PROVIDER_TOKEN", ""),
        payment_currency=os.getenv("PAYMENT_CURRENCY", "RUB"),
        premium_price_minor_units=parse_int(
            os.getenv("PREMIUM_PRICE_MINOR_UNITS"),
            default=49900,
        ),
        premium_product_title=os.getenv("PREMIUM_PRODUCT_TITLE", "Premium access"),
        premium_product_description=os.getenv(
            "PREMIUM_PRODUCT_DESCRIPTION",
            "Unlock premium chat modes and paid features.",
        ),
    )

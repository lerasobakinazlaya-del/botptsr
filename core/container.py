import logging
import socket
import time
from urllib.parse import urlparse

from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from database.db import Database
from database.memory_repository import MemoryRepository
from database.monetization_repository import MonetizationRepository
from database.openai_usage_repository import OpenAIUsageRepository
from database.payment_repository import PaymentRepository
from database.proactive_repository import ProactiveRepository
from database.repository import MessageRepository
from database.user_preference_repository import UserPreferenceRepository
from database.user_state_repository import UserStateRepository
from services.access_engine import AccessEngine
from services.ai_service import AIService
from services.admin_settings_service import AdminSettingsService
from services.chat_session_service import ChatSessionService
from services.conversation_engine_v2 import ConversationEngineV2
from services.conversation_summary_service import ConversationSummaryService
from services.human_memory_service import HumanMemoryService
from services.keyword_memory_service import KeywordMemoryService
from services.long_term_memory_service import LongTermMemoryService
from services.memory_engine import MemoryEngine
from services.memory_profile_service import MemoryProfileService
from services.mode_access_service import ModeAccessService
from services.openai_client import OpenAIClient
from services.payment_service import PaymentService
from services.proactive_message_service import ProactiveMessageService
from services.prompt_builder import PromptBuilder
from services.referral_service import ReferralService
from services.reengagement_service import ReengagementService
from services.state_engine import StateEngine
from services.user_service import UserService


LOGGER = logging.getLogger(__name__)


class Container:
    def __init__(self, settings):
        self.settings = settings

        self.db = Database()
        self.redis = self._create_redis_client()
        self.fsm_storage = (
            RedisStorage(redis=self.redis)
            if self.redis is not None
            else MemoryStorage()
        )

        self.message_repository = MessageRepository(self.db)
        self.memory_repository = MemoryRepository(self.db)
        self.monetization_repository = MonetizationRepository(self.db)
        self.openai_usage_repository = OpenAIUsageRepository(self.db)
        self.payment_repository = PaymentRepository(self.db)
        self.proactive_repository = ProactiveRepository(self.db)
        self.user_preference_repository = UserPreferenceRepository(self.db)
        self.state_repository = UserStateRepository(self.db)

        self.admin_settings_service = AdminSettingsService()
        self.chat_session_service = ChatSessionService()
        self.state_engine = StateEngine(self.admin_settings_service)
        self.memory_engine = MemoryEngine()
        self.keyword_memory_service = KeywordMemoryService()
        self.long_term_memory_service = LongTermMemoryService(
            repository=self.memory_repository,
            keyword_memory_service=self.keyword_memory_service,
            settings_service=self.admin_settings_service,
        )
        self.human_memory_service = HumanMemoryService()
        self.memory_profile_service = MemoryProfileService(
            long_term_memory_service=self.long_term_memory_service,
            redis=self.redis,
        )
        self.mode_access_service = ModeAccessService()
        self.conversation_engine = ConversationEngineV2(self.admin_settings_service)
        self.prompt_builder = PromptBuilder(
            self.admin_settings_service,
            conversation_engine=self.conversation_engine,
        )
        self.access_engine = AccessEngine(self.admin_settings_service)

        self.openai_client = OpenAIClient(
            api_key=self.settings.openai_api_key,
            max_parallel_requests=self.settings.openai_max_parallel_requests,
            usage_repository=self.openai_usage_repository,
        )
        self.ai_service = AIService(
            client=self.openai_client,
            state_engine=self.state_engine,
            memory_engine=self.memory_engine,
            keyword_memory_service=self.keyword_memory_service,
            long_term_memory_service=self.long_term_memory_service,
            human_memory_service=self.human_memory_service,
            memory_profile_service=self.memory_profile_service,
            prompt_builder=self.prompt_builder,
            access_engine=self.access_engine,
            settings_service=self.admin_settings_service,
            conversation_engine=self.conversation_engine,
            debug=self.settings.debug,
            log_full_prompt=self.settings.ai_log_full_prompt,
            debug_prompt_user_id=self.settings.ai_debug_prompt_user_id,
            max_parallel_requests=self.settings.openai_max_parallel_requests,
            queue_size=self.settings.openai_queue_size,
            queue_wait_timeout_seconds=self.settings.openai_queue_wait_timeout_seconds,
        )
        self.conversation_summary_service = ConversationSummaryService(
            client=self.openai_client,
            message_repository=self.message_repository,
            state_repository=self.state_repository,
            settings_service=self.admin_settings_service,
            long_term_memory_service=self.long_term_memory_service,
        )

        self.user_service = UserService(self.db, settings=self.settings)
        self.referral_service = ReferralService(
            db=self.db,
            user_service=self.user_service,
            settings_service=self.admin_settings_service,
            state_repository=self.state_repository,
        )
        self.payment_service = PaymentService(
            settings=self.settings,
            payment_repository=self.payment_repository,
            monetization_repository=self.monetization_repository,
            user_service=self.user_service,
            settings_service=self.admin_settings_service,
            referral_service=self.referral_service,
        )
        self.proactive_message_service = ProactiveMessageService(
            client=self.openai_client,
            message_repository=self.message_repository,
            proactive_repository=self.proactive_repository,
            user_preference_repository=self.user_preference_repository,
            state_repository=self.state_repository,
            long_term_memory_service=self.long_term_memory_service,
            keyword_memory_service=self.keyword_memory_service,
            memory_profile_service=self.memory_profile_service,
            prompt_builder=self.prompt_builder,
            conversation_engine=self.conversation_engine,
            access_engine=self.access_engine,
            settings_service=self.admin_settings_service,
            user_service=self.user_service,
        )
        self.reengagement_service = ReengagementService(
            ai_service=self.ai_service,
            message_repository=self.message_repository,
            state_repository=self.state_repository,
            user_preference_repository=self.user_preference_repository,
            proactive_repository=self.proactive_repository,
            user_service=self.user_service,
            settings_service=self.admin_settings_service,
            db=self.db,
        )

    def _create_redis_client(self) -> Redis | None:
        parsed = urlparse(self.settings.redis_url)
        host = parsed.hostname
        port = parsed.port or 6379

        if not host:
            LOGGER.warning("Redis host is missing, using in-memory fallback")
            return None

        last_exc: OSError | None = None
        delays = (0.25, 0.5, 1.0, 2.0, 4.0)
        for attempt, delay in enumerate(delays, start=1):
            try:
                with socket.create_connection((host, port), timeout=1.0):
                    LOGGER.info("Redis is reachable at %s:%s after %s attempt(s)", host, port, attempt)
                    return Redis.from_url(self.settings.redis_url)
            except OSError as exc:
                last_exc = exc
                LOGGER.warning(
                    "Redis connection attempt %s/%s failed at %s:%s: %s",
                    attempt,
                    len(delays),
                    host,
                    port,
                    exc,
                )
                if attempt < len(delays):
                    time.sleep(delay)

        LOGGER.warning(
            "Redis is unavailable at %s:%s after retries, using in-memory fallback: %s",
            host,
            port,
            last_exc,
        )
        return None

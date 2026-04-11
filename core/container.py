import logging
import socket
from urllib.parse import urlparse

from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from database.db import Database
from database.memory_repository import MemoryRepository
from database.monetization_repository import MonetizationRepository
from database.payment_repository import PaymentRepository
from database.proactive_repository import ProactiveRepository
from database.repository import MessageRepository
from database.user_preference_repository import UserPreferenceRepository
from database.user_state_repository import UserStateRepository
from services.access_engine import AccessEngine
from services.ai_service import AIService
from services.admin_settings_service import AdminSettingsService
from services.chat_session_service import ChatSessionService
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
        self.prompt_builder = PromptBuilder(self.admin_settings_service)
        self.access_engine = AccessEngine(self.admin_settings_service)

        self.openai_client = OpenAIClient(
            api_key=self.settings.openai_api_key,
            max_parallel_requests=self.settings.openai_max_parallel_requests,
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

        try:
            with socket.create_connection((host, port), timeout=1.0):
                LOGGER.info("Redis is reachable at %s:%s", host, port)
                return Redis.from_url(self.settings.redis_url)
        except OSError as exc:
            LOGGER.warning(
                "Redis is unavailable at %s:%s, using in-memory fallback: %s",
                host,
                port,
                exc,
            )
            return None

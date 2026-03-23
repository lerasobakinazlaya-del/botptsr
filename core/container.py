from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from database.db import Database
from database.payment_repository import PaymentRepository
from database.repository import MessageRepository
from database.user_state_repository import UserStateRepository
from services.access_engine import AccessEngine
from services.ai_service import AIService
from services.memory_engine import MemoryEngine
from services.keyword_memory_service import KeywordMemoryService
from services.openai_client import OpenAIClient
from services.payment_service import PaymentService
from services.prompt_builder import PromptBuilder
from services.state_engine import StateEngine
from services.user_service import UserService


class Container:
    def __init__(self, settings):
        self.settings = settings

        self.db = Database()
        self.redis = Redis.from_url(settings.redis_url)
        self.fsm_storage = RedisStorage(redis=self.redis)

        self.message_repository = MessageRepository(self.db)
        self.payment_repository = PaymentRepository(self.db)
        self.state_repository = UserStateRepository(self.db)

        self.state_engine = StateEngine()
        self.memory_engine = MemoryEngine()
        self.keyword_memory_service = KeywordMemoryService()
        self.prompt_builder = PromptBuilder()
        self.access_engine = AccessEngine()

        self.openai_client = OpenAIClient(api_key=self.settings.openai_api_key)
        self.ai_service = AIService(
            client=self.openai_client,
            state_engine=self.state_engine,
            memory_engine=self.memory_engine,
            keyword_memory_service=self.keyword_memory_service,
            prompt_builder=self.prompt_builder,
            access_engine=self.access_engine,
            debug=self.settings.debug,
            log_full_prompt=self.settings.ai_log_full_prompt,
            debug_prompt_user_id=self.settings.ai_debug_prompt_user_id,
            max_parallel_requests=self.settings.openai_max_parallel_requests,
            queue_size=self.settings.openai_queue_size,
        )

        self.user_service = UserService(self.db)
        self.payment_service = PaymentService(
            settings=self.settings,
            payment_repository=self.payment_repository,
            user_service=self.user_service,
        )

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery


class AdminFilter(BaseFilter):
    async def __call__(self, event, user_service) -> bool:
        return await user_service.is_admin(event.from_user.id)

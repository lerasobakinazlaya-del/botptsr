from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery


class AdminFilter(BaseFilter):
    async def __call__(self, event, settings) -> bool:
        user_id = event.from_user.id
        return user_id == settings.owner_id or user_id in settings.admin_id
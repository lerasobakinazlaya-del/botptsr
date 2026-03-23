from aiogram.fsm.state import State, StatesGroup


class PremiumStates(StatesGroup):
    waiting_for_give_user_id = State()
    waiting_for_remove_user_id = State()


class BroadcastStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_confirmation = State()

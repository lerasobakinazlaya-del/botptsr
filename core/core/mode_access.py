FREE_MODES = ["base", "ptsd", "comfort"]
PREMIUM_MODES = ["passion", "mentor", "night", "dominant"]


def resolve_mode(user):
    """
    Проверяет, может ли пользователь использовать выбранный режим.
    Если нет — возвращает base.
    """

    if user.active_mode in PREMIUM_MODES and not user.is_premium:
        return "base"

    return user.active_mode

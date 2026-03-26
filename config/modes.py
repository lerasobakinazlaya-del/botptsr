from dataclasses import dataclass

from services.admin_settings_service import AdminSettingsService


@dataclass(frozen=True)
class ModeConfig:
    key: str
    name: str
    icon: str
    description: str
    tone: str
    emotional_state: str
    behavior_rules: str
    activation_phrase: str
    is_premium: bool
    sort_order: int


_settings_service = AdminSettingsService()


def _load_mode_catalog() -> dict[str, ModeConfig]:
    catalog = _settings_service.get_mode_catalog()
    return {
        key: ModeConfig(
            key=value["key"],
            name=value["name"],
            icon=value["icon"],
            description=value["description"],
            tone=value["tone"],
            emotional_state=value["emotional_state"],
            behavior_rules=value["behavior_rules"],
            activation_phrase=value["activation_phrase"],
            is_premium=bool(value["is_premium"]),
            sort_order=int(value["sort_order"]),
        )
        for key, value in catalog.items()
    }


def get_modes() -> dict[str, ModeConfig]:
    return _load_mode_catalog()


def get_mode(mode_key: str) -> ModeConfig:
    modes = get_modes()
    return modes.get(mode_key, modes["base"])


def get_ordered_modes() -> list[ModeConfig]:
    return sorted(
        get_modes().values(),
        key=lambda item: (item.sort_order, item.name.lower()),
    )


def get_premium_modes() -> set[str]:
    return {mode.key for mode in get_modes().values() if mode.is_premium}

from config.modes import MODES, ModeConfig, get_mode


class ModeRegistry:
    def get(self, key: str) -> ModeConfig:
        return get_mode(key)

    def list(self) -> list[ModeConfig]:
        return list(MODES.values())


mode_registry = ModeRegistry()


def get_mode_config(key: str) -> ModeConfig:
    return mode_registry.get(key)

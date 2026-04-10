import json
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class ModeConfigError(Exception):
    pass


class ModeManager:
    def __init__(self, config_filename: str = "modes.json"):
        self._config_path = self._resolve_path(config_filename)
        self._modes: dict[str, Any] = {}
        self._mtime: float | None = None
        self._modes = self._load_modes(force=True)

    def _resolve_path(self, filename: str) -> Path:
        base_dir = Path(__file__).resolve().parent.parent
        return base_dir / "config" / filename

    def _load_modes(self, force: bool = False) -> dict[str, Any]:
        current_mtime = self._config_path.stat().st_mtime if self._config_path.exists() else None
        if not force and self._mtime is not None and self._mtime == current_mtime:
            return self._modes

        if not self._config_path.exists():
            logger.error("Modes config not found: %s", self._config_path)
            raise ModeConfigError(f"Modes config file not found: {self._config_path}")

        try:
            with open(self._config_path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            logger.exception("Invalid JSON in modes config")
            raise ModeConfigError("Invalid JSON in modes config") from exc

        if not isinstance(data, dict):
            raise ModeConfigError("Modes config must be a dictionary")

        if "base" not in data:
            raise ModeConfigError("Modes config must contain 'base' mode")

        logger.info("Loaded %d mode profiles", len(data))
        self._mtime = current_mtime
        self._modes = data
        return data

    def get(self, mode_name: str) -> dict[str, Any]:
        self._load_modes()
        alias_chain = [mode_name]
        if mode_name == "comfort":
            alias_chain.append("ptsd")
        elif mode_name == "ptsd":
            alias_chain.append("comfort")

        mode = None
        for candidate in alias_chain:
            mode = self._modes.get(candidate)
            if mode is not None:
                break
        if mode is None:
            logger.warning("Mode '%s' not found. Using 'base' fallback.", mode_name)
            return self._modes["base"]
        return mode

    def list_modes(self) -> dict[str, Any]:
        self._load_modes()
        return self._modes.copy()


mode_manager = ModeManager()


def get_mode_config(mode_name: str) -> dict[str, Any]:
    return mode_manager.get(mode_name)

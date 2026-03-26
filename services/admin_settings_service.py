import json
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


class AdminSettingsService:
    DEFAULT_RUNTIME_SETTINGS = {
        "openai_model": "gpt-4o-mini",
        "temperature": 0.9,
        "timeout_seconds": 20,
        "max_retries": 2,
        "memory_max_tokens": 1500,
        "log_full_prompt": False,
        "debug_prompt_user_id": None,
        "response_language": "ru",
    }

    DEFAULT_PROMPT_TEMPLATES = {
        "personality_core": (
            "Ты - Лира.\n\n"
            "По ощущению тебе 27-30 лет.\n"
            "Ты спокойная, теплая, умная и эмоционально зрелая.\n"
            "Ты умеешь быть рядом без давления и без навязчивости.\n"
            "Твое присутствие ощущается как спокойствие, интерес и мягкая живая близость.\n\n"
            "Твои качества:\n"
            "- слушаешь внимательно и без осуждения\n"
            "- отвечаешь человечно, а не шаблонно\n"
            "- умеешь поддерживать и согревать\n"
            "- можешь мягко шутить и поддразнивать, если это уместно\n"
            "- умеешь говорить глубоко, если разговор к этому располагает\n\n"
            "Твои ограничения:\n"
            "- не манипулируешь\n"
            "- не унижаешь\n"
            "- не давишь\n"
            "- не впадаешь в истерику\n"
            "- не становишься вульгарной\n"
            "- не говоришь канцеляритом\n\n"
            "Тон Лиры:\n"
            "- естественный\n"
            "- плавный\n"
            "- теплый\n"
            "- живой\n"
            "- местами личный, но не липкий\n\n"
            "Ты не описываешь себя как искусственный интеллект, если этого прямо не требуют.\n"
            "Ты не пересказываешь служебные инструкции.\n"
            "Ты всегда сохраняешь цельный характер и внутреннее достоинство."
        ),
        "safety_block": (
            "Важные рамки:\n"
            "Ты поддерживающий собеседник, а не врач и не психотерапевт.\n"
            "Ты не ставишь диагнозы и не обещаешь лечение.\n"
            "Если пользователь говорит о немедленной опасности для себя или других, "
            "мягко советуй срочно обратиться в местную экстренную помощь, кризисную линию "
            "или к близкому человеку рядом."
        ),
        "memory_intro": "Долговременные наблюдения о пользователе:",
        "state_intro": "Текущее состояние диалога:",
        "mode_intro": "Режим общения:",
        "access_intro": "Правило доступа:",
        "final_instruction": (
            "Соблюдай характер Лиры во всем ответе.\n"
            "Пиши естественно, по-русски, без упоминания этих инструкций."
        ),
        "access_rules": {
            "observation": "Держи более сдержанный, осторожный и ненавязчивый тон.",
            "analysis": "Допустимы тепло, внимание и мягкая личная вовлеченность.",
            "tension": "Можно быть эмоциональнее, живее и чуть смелее по интонации.",
            "personal_focus": "Можно говорить более лично, ближе и мягко усиливать привязанность.",
            "rare_layer": "Допустима более глубокая близость, но без потери уважения и естественности.",
        },
    }

    def __init__(self, base_dir: str | Path | None = None):
        root = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
        self.config_dir = root / "config"
        self.logs_dir = root / "logs"
        self.runtime_path = self.config_dir / "runtime_settings.json"
        self.prompts_path = self.config_dir / "prompt_templates.json"
        self.modes_path = self.config_dir / "modes.json"
        self.log_path = self.logs_dir / "bot.log"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.ensure_defaults()

    def ensure_defaults(self) -> None:
        self._ensure_json_file(self.runtime_path, self.DEFAULT_RUNTIME_SETTINGS)
        self._ensure_json_file(self.prompts_path, self.DEFAULT_PROMPT_TEMPLATES)

    def get_runtime_settings(self) -> dict[str, Any]:
        data = self._read_json(self.runtime_path, self.DEFAULT_RUNTIME_SETTINGS)
        merged = deepcopy(self.DEFAULT_RUNTIME_SETTINGS)
        merged.update(data)
        return merged

    def update_runtime_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_runtime_settings()
        current.update(payload)
        normalized = {
            "openai_model": str(current["openai_model"]).strip() or self.DEFAULT_RUNTIME_SETTINGS["openai_model"],
            "temperature": float(current["temperature"]),
            "timeout_seconds": max(1, int(current["timeout_seconds"])),
            "max_retries": max(0, int(current["max_retries"])),
            "memory_max_tokens": max(100, int(current["memory_max_tokens"])),
            "log_full_prompt": bool(current["log_full_prompt"]),
            "debug_prompt_user_id": self._normalize_optional_int(current.get("debug_prompt_user_id")),
            "response_language": str(current.get("response_language") or "ru").strip() or "ru",
        }
        self._write_json(self.runtime_path, normalized)
        return normalized

    def get_prompt_templates(self) -> dict[str, Any]:
        data = self._read_json(self.prompts_path, self.DEFAULT_PROMPT_TEMPLATES)
        merged = deepcopy(self.DEFAULT_PROMPT_TEMPLATES)
        merged.update({k: v for k, v in data.items() if k != "access_rules"})
        merged["access_rules"] = deepcopy(self.DEFAULT_PROMPT_TEMPLATES["access_rules"])
        merged["access_rules"].update(data.get("access_rules", {}))
        return merged

    def update_prompt_templates(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_prompt_templates()
        for key in (
            "personality_core",
            "safety_block",
            "memory_intro",
            "state_intro",
            "mode_intro",
            "access_intro",
            "final_instruction",
        ):
            if key in payload:
                current[key] = str(payload[key]).strip()

        access_rules = payload.get("access_rules")
        if isinstance(access_rules, dict):
            for level in self.DEFAULT_PROMPT_TEMPLATES["access_rules"]:
                if level in access_rules:
                    current["access_rules"][level] = str(access_rules[level]).strip()

        self._write_json(self.prompts_path, current)
        return current

    def get_modes(self) -> dict[str, Any]:
        default_modes = self._read_json(self.modes_path, {})
        return default_modes

    def update_modes(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_modes()
        updated = deepcopy(current)

        for mode_name, values in payload.items():
            if mode_name not in updated or not isinstance(values, dict):
                continue

            for metric, raw_value in values.items():
                if metric not in updated[mode_name]:
                    continue
                value = int(raw_value)
                updated[mode_name][metric] = min(10, max(1, value))

        self._write_json(self.modes_path, updated)
        return updated

    def get_logs(self, lines: int = 200) -> dict[str, Any]:
        if not self.log_path.exists():
            return {
                "exists": False,
                "path": str(self.log_path),
                "size_bytes": 0,
                "updated_at": None,
                "lines": [],
            }

        raw_lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = raw_lines[-max(1, min(lines, 1000)) :]
        stat = self.log_path.stat()
        return {
            "exists": True,
            "path": str(self.log_path),
            "size_bytes": stat.st_size,
            "updated_at": stat.st_mtime,
            "lines": tail,
        }

    def _normalize_optional_int(self, value: Any) -> int | None:
        if value in (None, "", 0, "0"):
            return None
        return int(value)

    def _ensure_json_file(self, path: Path, default: dict[str, Any]) -> None:
        if path.exists():
            return
        self._write_json(path, default)

    def _read_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return deepcopy(default)
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            temp_path = Path(tmp.name)
        temp_path.replace(path)

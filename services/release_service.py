from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_release_info(config_dir: Path) -> dict[str, Any]:
    path = Path(config_dir) / "release.json"
    if not path.exists():
        return {
            "path": str(path),
            "available": False,
            "branch": "",
            "commit": "",
            "deployed_at": "",
        }

    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        return {
            "path": str(path),
            "available": False,
            "branch": "",
            "commit": "",
            "deployed_at": "",
        }

    return {
        "path": str(path),
        "available": True,
        "branch": str(payload.get("branch") or "").strip(),
        "commit": str(payload.get("commit") or "").strip(),
        "deployed_at": str(payload.get("deployed_at") or "").strip(),
    }


def build_health_warnings(
    *,
    admin_dashboard_password: str,
    redis_ok: bool,
    release_info: dict[str, Any],
    runtime_stats: dict[str, Any],
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []

    if admin_dashboard_password.strip() in {"change-me", "change-this-strong-password", ""}:
        warnings.append(
            {
                "severity": "high",
                "code": "default_admin_password",
                "message": "У админки дефолтный или пустой пароль. Это нужно исправить до публичного доступа.",
            }
        )

    if not redis_ok:
        warnings.append(
            {
                "severity": "medium",
                "code": "redis_fallback",
                "message": "Redis недоступен. Бот работает, но часть runtime-кеша и middleware деградируют.",
            }
        )

    if not release_info.get("available"):
        warnings.append(
            {
                "severity": "low",
                "code": "missing_release_metadata",
                "message": "Нет release.json. Сложнее понять, какой код сейчас на проде.",
            }
        )

    queue_capacity = int(runtime_stats.get("queue_capacity") or 0)
    queue_size = int(runtime_stats.get("queue_size") or 0)
    if queue_capacity > 0 and queue_size / queue_capacity >= 0.8:
        warnings.append(
            {
                "severity": "medium",
                "code": "ai_queue_pressure",
                "message": "Очередь ИИ почти заполнена. Нужен контроль нагрузки или больше воркеров.",
            }
        )

    if int(runtime_stats.get("requests_rejected") or 0) > 0:
        warnings.append(
            {
                "severity": "high",
                "code": "ai_backpressure_rejections",
                "message": "Часть AI-запросов уже была отклонена из-за заполненной очереди. Это прямой сигнал, что текущей емкости не хватает.",
            }
        )

    if int(runtime_stats.get("requests_queue_timed_out") or 0) > 0:
        warnings.append(
            {
                "severity": "medium",
                "code": "ai_queue_wait_timeout",
                "message": "Запросы успевали застревать в очереди AI дольше допустимого времени. Под нагрузкой пользователи будут чаще видеть busy-ответы.",
            }
        )

    if int(runtime_stats.get("openai_waiting_requests") or 0) > 0:
        warnings.append(
            {
                "severity": "medium",
                "code": "openai_global_waiters",
                "message": "Есть ожидание на общем лимите OpenAI. Чат и фоновые задачи конкурируют за один и тот же пул запросов.",
            }
        )

    return warnings

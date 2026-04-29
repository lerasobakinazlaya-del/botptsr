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
    openai_usage: dict[str, Any] | None = None,
    usage_alerts: dict[str, Any] | None = None,
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

    usage = openai_usage or {}
    alerts = usage_alerts or {}
    if bool(alerts.get("enabled", True)):
        tokens_1d = int(usage.get("tokens_1d") or 0)
        requests_1d = int(usage.get("requests_1d") or 0)
        daily_tokens_warn = int(alerts.get("daily_tokens_warn") or 0)
        daily_tokens_high = int(alerts.get("daily_tokens_high") or 0)
        daily_requests_warn = int(alerts.get("daily_requests_warn") or 0)

        if daily_tokens_high > 0 and tokens_1d >= daily_tokens_high:
            warnings.append(
                {
                    "severity": "high",
                    "code": "openai_daily_tokens_high",
                    "message": f"OpenAI за 24 часа сжёг {tokens_1d} токенов. Это уже выше аварийного порога {daily_tokens_high}.",
                }
            )
        elif daily_tokens_warn > 0 and tokens_1d >= daily_tokens_warn:
            warnings.append(
                {
                    "severity": "medium",
                    "code": "openai_daily_tokens_warn",
                    "message": f"OpenAI за 24 часа сжёг {tokens_1d} токенов. Проверь, не разогнались ли фоновые источники.",
                }
            )

        if daily_requests_warn > 0 and requests_1d >= daily_requests_warn:
            warnings.append(
                {
                    "severity": "medium",
                    "code": "openai_daily_requests_warn",
                    "message": f"OpenAI сделал {requests_1d} вызовов за 24 часа. Это выше ожидаемого порога и требует разреза по source.",
                }
            )

        source_daily_tokens_warn = int(alerts.get("source_daily_tokens_warn") or 0)
        source_daily_requests_warn = int(alerts.get("source_daily_requests_warn") or 0)
        source_share_warn_pct = int(alerts.get("source_share_warn_pct") or 0)
        excluded_sources = {
            str(item).strip()
            for item in (alerts.get("excluded_sources") or [])
            if str(item).strip()
        }
        for source, payload in sorted(
            (usage.get("by_source_1d") or {}).items(),
            key=lambda item: int((item[1] or {}).get("total_tokens") or 0),
            reverse=True,
        )[:5]:
            normalized_source = str(source or "").strip() or "unknown"
            if normalized_source in excluded_sources:
                continue
            source_tokens = int((payload or {}).get("total_tokens") or 0)
            source_requests = int((payload or {}).get("requests") or 0)
            reasons: list[str] = []
            if source_daily_tokens_warn > 0 and source_tokens >= source_daily_tokens_warn:
                reasons.append(f"{source_tokens} токенов")
            if source_daily_requests_warn > 0 and source_requests >= source_daily_requests_warn:
                reasons.append(f"{source_requests} вызовов")
            share_pct = round((source_tokens / tokens_1d) * 100.0, 1) if tokens_1d > 0 else 0.0
            if source_share_warn_pct > 0 and share_pct >= source_share_warn_pct:
                reasons.append(f"{share_pct}% дневного расхода")
            if not reasons:
                continue
            warnings.append(
                {
                    "severity": "medium",
                    "code": "openai_source_spike",
                    "message": f"Источник {normalized_source} выбивается по расходу OpenAI: {', '.join(reasons)} за последние 24 часа.",
                }
            )

    return warnings

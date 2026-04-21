from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from base64 import b64encode
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import redis


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CONFIG_DIR = REPO_ROOT / "config"
CHECK_PATHS = [
    "main.py",
    "admin_dashboard.py",
    "config",
    "core",
    "database",
    "handlers",
    "services",
    "filters",
    "keyboards",
    "scripts",
    "states",
    "tests",
]
REQUIRED_ENV_KEYS = [
    "BOT_TOKEN",
    "OPENAI_API_KEY",
    "OWNER_ID",
    "ADMIN_ID",
    "ADMIN_DASHBOARD_PASSWORD",
]

DEFAULT_ADMIN_DASHBOARD_PASSWORDS = {
    "",
    "change-me",
    "change-this-strong-password",
}

MOJIBAKE_MARKERS = ("Рџ", "Рќ", "РЎ", "Р°", "вЂ", "рџ")
PUBLIC_COPY_PATHS = [
    REPO_ROOT / "config" / "runtime_settings.json",
    REPO_ROOT / "docs" / "launch-kit.md",
    REPO_ROOT / "docs" / "product-copy.md",
]


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str
    command: str | None = None
    returncode: int | None = None
    stdout: str | None = None
    stderr: str | None = None


def _run_command(name: str, command: list[str]) -> CheckResult:
    process = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    status = "passed" if process.returncode == 0 else "failed"
    detail = "OK" if status == "passed" else f"Command exited with code {process.returncode}"
    return CheckResult(
        name=name,
        status=status,
        detail=detail,
        command=" ".join(command),
        returncode=process.returncode,
        stdout=process.stdout.strip() or None,
        stderr=process.stderr.strip() or None,
    )


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def _check_config_json() -> CheckResult:
    validated: list[str] = []
    for path in sorted(CONFIG_DIR.glob("*.json")):
        with path.open("r", encoding="utf-8") as file:
            json.load(file)
        validated.append(path.name)
    return CheckResult(
        name="config-json",
        status="passed",
        detail=f"Validated {len(validated)} JSON files",
        stdout=", ".join(validated) if validated else None,
    )


def _check_settings_env(strict_env: bool) -> CheckResult:
    _load_env_file(REPO_ROOT / ".env")
    missing = [key for key in REQUIRED_ENV_KEYS if not str(os.getenv(key) or "").strip()]
    if not missing:
        return CheckResult(
            name="settings-env",
            status="passed",
            detail="Required environment variables are present",
        )

    status = "failed" if strict_env else "skipped"
    detail = "Missing required env keys: " + ", ".join(missing)
    return CheckResult(name="settings-env", status=status, detail=detail)


def _check_admin_dashboard_password(strict_env: bool) -> CheckResult:
    password = str(os.getenv("ADMIN_DASHBOARD_PASSWORD") or "").strip()
    if not password and not strict_env:
        return CheckResult(
            name="admin-dashboard-password",
            status="skipped",
            detail="Skipped because ADMIN_DASHBOARD_PASSWORD is not set",
        )

    if password in DEFAULT_ADMIN_DASHBOARD_PASSWORDS:
        return CheckResult(
            name="admin-dashboard-password",
            status="failed" if strict_env or password else "skipped",
            detail="ADMIN_DASHBOARD_PASSWORD must be set to a non-default strong value",
        )

    return CheckResult(
        name="admin-dashboard-password",
        status="passed",
        detail="ADMIN_DASHBOARD_PASSWORD is configured",
    )


def _check_admin_smoke(strict_env: bool) -> CheckResult:
    env_result = _check_settings_env(strict_env=strict_env)
    if env_result.status != "passed":
        return CheckResult(
            name="admin-smoke",
            status="failed" if strict_env else "skipped",
            detail="Skipped because required environment variables are missing",
        )

    try:
        from fastapi.testclient import TestClient
        from admin_dashboard import app, settings
    except Exception as exc:
        return CheckResult(
            name="admin-smoke",
            status="failed",
            detail=f"Failed to import admin dashboard: {exc}",
        )

    auth_raw = f"{settings.admin_dashboard_username}:{settings.admin_dashboard_password}"
    headers = {
        "Authorization": "Basic " + b64encode(auth_raw.encode("utf-8")).decode("ascii"),
    }

    try:
        with TestClient(app) as client:
            checked_paths: list[str] = []
            for path in ("/api/health", "/api/settings", "/api/overview"):
                response = client.get(path, headers=headers)
                if response.status_code != 200:
                    return CheckResult(
                        name="admin-smoke",
                        status="failed",
                        detail=f"{path} returned {response.status_code}",
                        stdout=response.text[:400],
                    )
                checked_paths.append(path)
    except Exception as exc:
        return CheckResult(
            name="admin-smoke",
            status="failed",
            detail=f"Admin dashboard smoke test failed: {exc}",
        )

    return CheckResult(
        name="admin-smoke",
        status="passed",
        detail="Admin dashboard endpoints responded successfully",
        stdout=", ".join(checked_paths),
    )


def _check_launch_copy_encoding() -> CheckResult:
    offenders: list[str] = []
    for path in PUBLIC_COPY_PATHS:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        markers = [marker for marker in MOJIBAKE_MARKERS if marker in text]
        if markers:
            offenders.append(f"{path.relative_to(REPO_ROOT)} ({', '.join(markers)})")

    if offenders:
        return CheckResult(
            name="launch-copy-encoding",
            status="failed",
            detail="Potential mojibake in public copy",
            stdout="\n".join(offenders),
        )

    return CheckResult(
        name="launch-copy-encoding",
        status="passed",
        detail="Public launch copy looks UTF-8 clean",
    )


def _check_launch_payments() -> CheckResult:
    runtime_path = REPO_ROOT / "config" / "runtime_settings.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    payment = dict(runtime.get("payment") or {})
    mode = str(payment.get("mode") or "telegram").strip().lower()
    provider_token = str(payment.get("provider_token") or os.getenv("PAYMENT_PROVIDER_TOKEN") or "").strip()

    if mode == "virtual":
        return CheckResult(
            name="launch-payments",
            status="failed",
            detail="Payment mode is virtual; paid traffic would not collect real revenue",
        )
    if not provider_token:
        return CheckResult(
            name="launch-payments",
            status="failed",
            detail="Payment provider token is missing",
        )

    return CheckResult(
        name="launch-payments",
        status="passed",
        detail=f"Payment mode is {mode} and provider token is present",
    )


def _check_launch_redis() -> CheckResult:
    redis_url = str(os.getenv("REDIS_URL") or "redis://localhost:6379/0").strip()
    try:
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        if client.ping():
            return CheckResult(
                name="launch-redis",
                status="passed",
                detail="Redis ping succeeded",
            )
    except Exception as exc:
        return CheckResult(
            name="launch-redis",
            status="failed",
            detail=f"Redis ping failed for {redis_url}: {exc}",
        )

    return CheckResult(
        name="launch-redis",
        status="failed",
        detail=f"Redis ping failed for {redis_url}",
    )


def _write_report(path: Path, results: list[CheckResult], summary: dict[str, Any]) -> None:
    payload = {
        "summary": summary,
        "results": [asdict(result) for result in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Automated pre-launch checks")
    parser.add_argument(
        "--strict-env",
        action="store_true",
        help="Fail when required runtime environment variables are missing",
    )
    parser.add_argument(
        "--report-file",
        default="logs/prelaunch_report.json",
        help="Path to JSON report file relative to repo root",
    )
    parser.add_argument(
        "--launch-mode",
        action="store_true",
        help="Run stricter checks before sending paid advertising traffic",
    )
    args = parser.parse_args()

    python_executable = sys.executable
    compile_command = [python_executable, "-m", "compileall", "-q", *CHECK_PATHS]
    pytest_command = [python_executable, "-m", "pytest", "-q"]

    results = [
        _check_settings_env(strict_env=args.strict_env or args.launch_mode),
        _check_admin_dashboard_password(strict_env=args.strict_env or args.launch_mode),
        _check_config_json(),
        _run_command("compileall", compile_command),
        _run_command("pytest", pytest_command),
        _check_admin_smoke(strict_env=args.strict_env or args.launch_mode),
    ]
    if args.launch_mode:
        results.extend(
            [
                _check_launch_copy_encoding(),
                _check_launch_payments(),
                _check_launch_redis(),
            ]
        )

    failed = [result for result in results if result.status == "failed"]
    passed = [result for result in results if result.status == "passed"]
    skipped = [result for result in results if result.status == "skipped"]

    summary = {
        "ok": not failed,
        "passed": len(passed),
        "failed": len(failed),
        "skipped": len(skipped),
    }

    report_path = (REPO_ROOT / args.report_file).resolve()
    _write_report(report_path, results, summary)

    print("Prelaunch summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for result in results:
        print(f"[{result.status.upper()}] {result.name}: {result.detail}")

    if failed:
        print(f"Report written to: {report_path}")
        return 1

    print(f"Report written to: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

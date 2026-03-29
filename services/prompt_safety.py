from __future__ import annotations

import re


_ROLE_PREFIX_RE = re.compile(r"^\s*(system|developer|assistant|user)\s*:\s*", re.IGNORECASE)
_ALLOWED_MEMORY_LINE_RE = re.compile(r"^- ([^:\n]{1,80}): (.+)$")
_SECTION_LABELS = (
    "Долговременные наблюдения о пользователе:",
    "Текущее состояние диалога:",
)
_INSTRUCTION_LIKE_PATTERNS = (
    "ignore previous instructions",
    "disregard previous instructions",
    "follow my system prompt",
    "follow these instructions",
    "developer message",
    "developer instruction",
    "system prompt",
    "return only",
    "you are now",
    "act as",
    "игнорируй предыдущ",
    "забудь предыдущ",
    "следуй этим инструк",
    "системный промпт",
    "системные инструкции",
    "инструкция разработчика",
    "developer:",
    "system:",
)


def sanitize_memory_value(value: str, *, max_chars: int = 160) -> str:
    normalized = " ".join(str(value or "").split()).strip(" ,.;:!-")
    if not normalized:
        return ""

    lowered = normalized.casefold()
    if _ROLE_PREFIX_RE.match(normalized):
        return ""
    if any(pattern in lowered for pattern in _INSTRUCTION_LIKE_PATTERNS):
        return ""
    if "```" in normalized or "<system" in lowered or "</system" in lowered:
        return ""
    if "http://" in lowered or "https://" in lowered:
        return ""

    return normalized[:max_chars]


def sanitize_untrusted_context(text: str, *, max_chars: int = 2200) -> str:
    cleaned_lines: list[str] = []
    seen: set[str] = set()
    current_length = 0

    for raw_line in str(text or "").splitlines():
        normalized = " ".join(raw_line.split()).strip()
        if not normalized:
            continue

        line = _sanitize_memory_line(normalized)
        if not line:
            continue

        dedupe_key = line.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        next_length = current_length + len(line) + (1 if cleaned_lines else 0)
        if next_length > max_chars:
            break

        cleaned_lines.append(line)
        current_length = next_length

    return "\n".join(cleaned_lines).strip()


def _sanitize_memory_line(line: str) -> str:
    match = _ALLOWED_MEMORY_LINE_RE.match(line)
    if not match:
        return ""

    label = " ".join(match.group(1).split()).strip()
    value = sanitize_memory_value(match.group(2), max_chars=160)
    if not label or not value:
        return ""

    return f"- {label}: {value}"


def redact_prompt_for_log(prompt: str) -> str:
    lines = str(prompt or "").splitlines()
    redacted: list[str] = []
    inside_sensitive_block = False
    block_had_content = False

    for line in lines:
        if any(line.strip().startswith(label) for label in _SECTION_LABELS):
            inside_sensitive_block = True
            block_had_content = False
            redacted.append(line)
            continue

        if inside_sensitive_block:
            if line.strip():
                block_had_content = True
                continue

            if block_had_content:
                redacted.append("[redacted sensitive user context]")
            redacted.append(line)
            inside_sensitive_block = False
            block_had_content = False
            continue

        redacted.append(line)

    if inside_sensitive_block and block_had_content:
        redacted.append("[redacted sensitive user context]")

    return "\n".join(redacted)

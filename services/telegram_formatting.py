from __future__ import annotations

import html
import re
from dataclasses import dataclass


_FENCED_CODE_RE = re.compile(r"```(?:[^\n`]*)\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(
    r"\[([^\]\n]+)\]\(((?:https?://|tg://|mailto:)[^\s)]+)\)"
)

_BOLD_PATTERNS = (
    re.compile(r"\*\*([^\n*][^\n]*?[^\n*])\*\*"),
    re.compile(r"__([^\n_][^\n]*?[^\n_])__"),
)
_ITALIC_PATTERNS = (
    re.compile(r"(?<!\*)\*([^*\n][^*\n]*?[^*\n])\*(?!\*)"),
    re.compile(r"(?<![\w_])_([^_\n][^_\n]*?[^_\n])_(?![\w_])"),
)
_STRIKE_RE = re.compile(r"~~([^\n~][^\n]*?[^\n~])~~")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+)$")
_UNORDERED_LIST_RE = re.compile(r"^\s*[-*]\s+")
_ORDERED_LIST_RE = re.compile(r"^\s*(\d+)[.)]\s+")


@dataclass(frozen=True)
class TelegramFormattingOptions:
    allow_bold: bool = False
    allow_italic: bool = False


def format_model_response_for_telegram(
    text: str,
    options: TelegramFormattingOptions | None = None,
) -> str:
    normalized = (text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""

    options = options or TelegramFormattingOptions()
    placeholders: dict[str, str] = {}

    def stash(value: str) -> str:
        token = f"\uFFF0{len(placeholders)}\uFFF1"
        placeholders[token] = value
        return token

    normalized = _FENCED_CODE_RE.sub(
        lambda match: stash(_render_code_block(match.group(1))),
        normalized,
    )
    normalized = _INLINE_CODE_RE.sub(
        lambda match: stash(f"<code>{html.escape(match.group(1), quote=False)}</code>"),
        normalized,
    )
    normalized = _LINK_RE.sub(
        lambda match: stash(_render_link(match.group(1), match.group(2))),
        normalized,
    )

    escaped = html.escape(normalized, quote=False)
    escaped = _apply_block_transforms(escaped, options)
    escaped = _apply_inline_transforms(escaped, options)

    for token, value in placeholders.items():
        escaped = escaped.replace(token, value)

    return escaped


def escape_plain_text_for_telegram(text: str) -> str:
    return html.escape((text or "").replace("\r\n", "\n"), quote=False)


def _render_code_block(code: str) -> str:
    rendered = html.escape(code.rstrip("\n"), quote=False)
    return f"<pre><code>{rendered}</code></pre>"


def _render_link(label: str, url: str) -> str:
    safe_label = html.escape(label.strip(), quote=False)
    safe_url = html.escape(url.strip(), quote=True)
    return f'<a href="{safe_url}">{safe_label}</a>'


def _apply_block_transforms(
    text: str,
    options: TelegramFormattingOptions,
) -> str:
    lines: list[str] = []

    for line in text.split("\n"):
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            heading_text = heading_match.group(1).strip()
            if options.allow_bold:
                lines.append(f"<b>{heading_text}</b>")
            else:
                lines.append(heading_text)
            continue

        if _UNORDERED_LIST_RE.match(line):
            lines.append(_UNORDERED_LIST_RE.sub("- ", line, count=1))
            continue

        ordered_match = _ORDERED_LIST_RE.match(line)
        if ordered_match:
            prefix = f"{ordered_match.group(1)}. "
            lines.append(_ORDERED_LIST_RE.sub(prefix, line, count=1))
            continue

        lines.append(line)

    return "\n".join(lines)


def _apply_inline_transforms(
    text: str,
    options: TelegramFormattingOptions,
) -> str:
    formatted = text

    if options.allow_bold:
        for pattern in _BOLD_PATTERNS:
            formatted = _apply_repeated(pattern, "b", formatted)
    else:
        for pattern in _BOLD_PATTERNS:
            formatted = _strip_repeated(pattern, formatted)

    formatted = _apply_repeated(_STRIKE_RE, "s", formatted)

    if options.allow_italic:
        for pattern in _ITALIC_PATTERNS:
            formatted = _apply_repeated(pattern, "i", formatted)
    else:
        for pattern in _ITALIC_PATTERNS:
            formatted = _strip_repeated(pattern, formatted)

    return formatted


def _apply_repeated(pattern: re.Pattern[str], tag: str, text: str) -> str:
    current = text
    while True:
        updated = pattern.sub(lambda match: f"<{tag}>{match.group(1)}</{tag}>", current)
        if updated == current:
            return updated
        current = updated


def _strip_repeated(pattern: re.Pattern[str], text: str) -> str:
    current = text
    while True:
        updated = pattern.sub(lambda match: match.group(1), current)
        if updated == current:
            return updated
        current = updated

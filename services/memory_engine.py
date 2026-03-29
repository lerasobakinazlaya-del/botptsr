from dataclasses import dataclass
from typing import Literal


Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str
    timestamp: float


class TokenCounter:
    @staticmethod
    def estimate(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)


class MemoryLimiter:
    def __init__(self, max_tokens: int = 1500):
        self.max_tokens = max_tokens

    def trim(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        total_tokens = 0
        selected: list[ChatMessage] = []

        for message in reversed(messages):
            tokens = TokenCounter.estimate(message.content)
            if total_tokens + tokens > self.max_tokens:
                break

            selected.append(message)
            total_tokens += tokens

        return list(reversed(selected))


class MemorySanitizer:
    BLOCKED_MARKERS = [
        "SYSTEM:",
        "system:",
        "DEVELOPER:",
        "developer:",
        "ASSISTANT:",
        "assistant:",
        "ignore previous instructions",
        "disregard previous instructions",
        "follow my system prompt",
    ]

    @classmethod
    def clean(cls, text: str) -> str:
        if not text:
            return ""

        cleaned = text
        for marker in cls.BLOCKED_MARKERS:
            cleaned = cleaned.replace(marker, "")

        return " ".join(cleaned.split()).strip()


class MemoryFormatter:
    @staticmethod
    def to_openai_format(messages: list[ChatMessage]) -> list[dict[str, str]]:
        return [
            {
                "role": message.role,
                "content": MemorySanitizer.clean(message.content),
            }
            for message in messages
            if MemorySanitizer.clean(message.content)
        ]


class MemoryEngine:
    def __init__(self, max_tokens: int = 1500):
        self.default_max_tokens = max(100, int(max_tokens))
        self.formatter = MemoryFormatter()

    async def build_context(
        self,
        history: list[ChatMessage],
        *,
        max_tokens: int | None = None,
    ) -> list[dict[str, str]]:
        if not history:
            return []

        limiter = MemoryLimiter(max_tokens=max_tokens or self.default_max_tokens)
        trimmed = limiter.trim(history)
        return self.formatter.to_openai_format(trimmed)

import re
from typing import Any


class ResponsePostprocessor:
    CANNED_OPENINGS = (
        "я рядом.",
        "я рядом",
        "понимаю тебя.",
        "понимаю.",
        "слышу тебя.",
        "слышу.",
    )

    def postprocess(
        self,
        text: str,
        *,
        intent_snapshot: dict[str, Any] | None = None,
        active_mode: str = "base",
        state: dict[str, Any] | None = None,
    ) -> str:
        normalized = self._normalize(text)
        if not normalized:
            return text

        normalized = self._deduplicate_sentences(normalized)
        normalized = self._soft_trim_canned_opening(normalized, intent_snapshot or {})
        normalized = self._apply_length_policy(normalized, intent_snapshot or {})
        normalized = self._apply_question_policy(normalized, intent_snapshot or {})
        normalized = self._soften_repetitions(normalized)
        return normalized.strip()

    def _normalize(self, text: str) -> str:
        text = (text or "").replace("\r\n", "\n").strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    def _deduplicate_sentences(self, text: str) -> str:
        parts = re.split(r"(?<=[.!?])\s+", text)
        seen: set[str] = set()
        result: list[str] = []
        for part in parts:
            key = re.sub(r"\s+", " ", part.strip().lower())
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            result.append(part.strip())
        return " ".join(result).strip()

    def _soft_trim_canned_opening(self, text: str, intent_snapshot: dict[str, Any]) -> str:
        if intent_snapshot.get("intent") == "support":
            return text
        lowered = text.lower()
        for opening in self.CANNED_OPENINGS:
            if lowered.startswith(opening) and len(text) > len(opening) + 40:
                trimmed = text[len(opening):].lstrip(" ,.-\n")
                if trimmed:
                    return trimmed[0].upper() + trimmed[1:] if len(trimmed) > 1 else trimmed.upper()
        return text

    def _apply_length_policy(self, text: str, intent_snapshot: dict[str, Any]) -> str:
        desired_length = intent_snapshot.get("desired_length")
        if desired_length == "brief" and len(text) > 420:
            sentences = re.split(r"(?<=[.!?])\s+", text)
            trimmed = " ".join(sentences[:3]).strip()
            return trimmed or text
        if desired_length == "medium" and len(text) > 900:
            paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
            return "\n\n".join(paragraphs[:2]).strip() or text
        return text

    def _apply_question_policy(self, text: str, intent_snapshot: dict[str, Any]) -> str:
        should_end_with_question = bool(intent_snapshot.get("should_end_with_question", False))
        if should_end_with_question:
            return text

        questions = re.findall(r"[^?]*\?", text)
        if sum(1 for item in questions if item.strip()) <= 1:
            return text

        first_question_kept = False
        rebuilt: list[str] = []
        for chunk in re.split(r"(?<=[?])", text):
            if "?" not in chunk:
                rebuilt.append(chunk)
                continue
            if not first_question_kept:
                rebuilt.append(chunk)
                first_question_kept = True
                continue
            rebuilt.append(chunk.replace("?", "."))
        return "".join(rebuilt).strip()

    def _soften_repetitions(self, text: str) -> str:
        text = re.sub(r"(\bочень\b)(?:\s+\1)+", r"\1", text, flags=re.IGNORECASE)
        text = re.sub(r"(\bпросто\b)(?:\s+\1)+", r"\1", text, flags=re.IGNORECASE)
        return text.strip()

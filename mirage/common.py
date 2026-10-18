from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4


def uid() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def after(seconds: int) -> str:
    return (
        (datetime.now(UTC) + timedelta(seconds=seconds))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def canonical(value: Any) -> bytes:
    def normalize(item: Any) -> Any:
        if isinstance(item, str):
            return unicodedata.normalize("NFC", item)
        if isinstance(item, list):
            return [normalize(x) for x in item]
        if isinstance(item, dict):
            result: dict[str, Any] = {}
            for key, val in item.items():
                normalized = unicodedata.normalize("NFC", key)
                if normalized in result:
                    raise ValueError("Duplicate normalized key")
                result[normalized] = normalize(val)
            return result
        return item

    return json.dumps(
        normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def redact(text: str) -> str:
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+\S+", r"\1 [redacted]", text)
    text = re.sub(
        r"(?i)\b(token|password|secret|api[_-]?key|authorization)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        text,
    )
    return text[:2048]


class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)

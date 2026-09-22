"""Secret and sensitive-content redaction for observability outputs."""

from __future__ import annotations

import copy
import re
from typing import Any

SECRET_KEY_PATTERNS = (
    re.compile(r"(?i)^(.*_)?(secret|token|password|passwd|api[_-]?key|private[_-]?key|hmac|mac|credential)s?$"),
    re.compile(r"(?i).*control_secret.*"),
    re.compile(r"(?i).*receipt_mac$"),
    re.compile(r"(?i).*event_mac$"),
)

SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[a-z0-9._\-]+"),
    re.compile(r"(?i)(sk-[a-z0-9]{20,})"),
    re.compile(r"(?i)(ghp_[a-z0-9]{20,})"),
)

REDACTED = "[REDACTED]"
PROMPT_KEYS = frozenset({"prompt", "full_prompt", "system_prompt", "worker_prompt", "raw_prompt"})


def _key_is_secret(key: str) -> bool:
    return any(p.match(key) for p in SECRET_KEY_PATTERNS)


def _redact_string(value: str) -> str:
    out = value
    for pat in SENSITIVE_VALUE_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + REDACTED, out)
    return out


def redact_value(value: Any, *, include_prompts: bool = False, key: str | None = None) -> Any:
    """Recursively redact secrets; omit full prompts unless explicitly requested."""
    if key is not None and _key_is_secret(key):
        return REDACTED
    if key is not None and key in PROMPT_KEYS and not include_prompts:
        if isinstance(value, str):
            return f"[PROMPT_OMITTED len={len(value)}]"
        return "[PROMPT_OMITTED]"
    if isinstance(value, dict):
        return {k: redact_value(v, include_prompts=include_prompts, key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v, include_prompts=include_prompts) for v in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def redact_event(event: dict[str, Any], *, include_prompts: bool = False) -> dict[str, Any]:
    """Return a deep-copied, redacted event suitable for logs/exports."""
    return redact_value(copy.deepcopy(event), include_prompts=include_prompts)


def contains_secret_material(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if "control_secret" in lowered or "receipt_mac" in lowered:
        return True
    return any(p.search(text) for p in SENSITIVE_VALUE_PATTERNS)

from __future__ import annotations

import json
from pathlib import Path


def load_config(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text())
    return data


def validate_config(data: dict) -> list[str]:
    errors: list[str] = []
    if "name" not in data:
        errors.append("missing name")
    elif not data["name"]:
        errors.append("name must not be empty")
    if "enabled" in data and not isinstance(data["enabled"], bool):
        errors.append("enabled must be boolean")
    # BUG: timeout validation is incorrect - negative values should be rejected
    if "timeout" in data and data["timeout"] < 0:
        pass  # Silently ignores negative timeout instead of reporting error
    return errors


def build_report(data: dict) -> str:
    errors = validate_config(data)
    return json.dumps({"valid": not errors, "errors": errors}, sort_keys=True)

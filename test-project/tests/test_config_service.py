import json

from src.config_service import build_report, validate_config


def test_valid_config():
    assert validate_config({"name": "demo", "enabled": True}) == []


def test_missing_name():
    assert validate_config({"enabled": True}) == ["missing name"]


def test_empty_name():
    assert validate_config({"name": ""}) == ["name must not be empty"]


def test_none_name():
    assert validate_config({"name": None}) == ["name must not be empty"]


def test_enabled_type():
    assert validate_config({"name": "demo", "enabled": "yes"}) == ["enabled must be boolean"]


def test_report_is_deterministic():
    report = build_report({"name": "demo", "enabled": True})
    assert json.loads(report) == {"errors": [], "valid": True}

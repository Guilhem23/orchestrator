"""
Tests for Semantic Versioning Enforcement script (scripts/verify_semver.py).
"""

import subprocess
import sys
from pathlib import Path
import pytest

from scripts.verify_semver import SEMVER_REGEX, verify_semver


def test_semver_regex_valid_and_invalid():
    # Valid SemVer 2.0.0
    assert SEMVER_REGEX.match("0.1.0")
    assert SEMVER_REGEX.match("0.5.0")
    assert SEMVER_REGEX.match("1.0.0")
    assert SEMVER_REGEX.match("1.0.0-alpha.1")
    assert SEMVER_REGEX.match("1.0.0+20130313144700")

    # Invalid SemVer
    assert not SEMVER_REGEX.match("v1.0.0")  # 'v' prefix is not part of semver string itself
    assert not SEMVER_REGEX.match("1.0")     # missing patch
    assert not SEMVER_REGEX.match("01.0.0")   # leading zero on major not allowed if multi-digit
    assert not SEMVER_REGEX.match("beta")


def test_verify_semver_in_current_repo():
    repo_root = Path(__file__).resolve().parent.parent
    ret = verify_semver(repo_dir=repo_root)
    assert ret == 0


def test_verify_semver_catches_mismatch(tmp_path: Path):
    # Setup corrupted repo directory
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "0.5.0"\n')

    pkg_dir = tmp_path / "slice_orchestrator"
    pkg_dir.mkdir()
    init_file = pkg_dir / "__init__.py"
    init_file.write_text('__version__ = "0.4.0"\n')  # Mismatch!

    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [0.5.0]\n- Initial changes\n")

    ret = verify_semver(repo_dir=tmp_path)
    assert ret == 1

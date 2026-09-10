"""
Tests for path semantics and pattern matching (git_pathspec_v1).
"""

import pytest
from slice_orchestrator.path_semantics import (
    PathSemanticsError,
    check_path_collisions,
    match_path_pattern,
    normalize_repo_path,
)


def test_normalize_repo_path_valid():
    assert normalize_repo_path("src/foo.py") == "src/foo.py"
    assert normalize_repo_path("src/a/b/c.py") == "src/a/b/c.py"


def test_normalize_repo_path_invalid():
    with pytest.raises(PathSemanticsError):
        normalize_repo_path("/etc/passwd")

    with pytest.raises(PathSemanticsError):
        normalize_repo_path("../outside.py")

    with pytest.raises(PathSemanticsError):
        normalize_repo_path("./src/bar.py")


def test_check_path_collisions():
    # No collision
    check_path_collisions(["src/foo.py", "src/bar.py"])

    # Collision
    with pytest.raises(PathSemanticsError):
        check_path_collisions(["src/foo.py", "SRC/FOO.PY"])


def test_match_path_pattern():
    assert match_path_pattern("src/slice_orchestrator/cli.py", "src/**")
    assert match_path_pattern("docs/10_SLICE_ORCHESTRATOR.md", "docs/*.md")
    assert not match_path_pattern(".orchestrator/policy.yaml", "src/**")

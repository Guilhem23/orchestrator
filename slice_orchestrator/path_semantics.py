"""
Method v4 Deterministic Path Semantics (git_pathspec_v1)
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Sequence


class PathSemanticsError(ValueError):
    """Raised when a path or pattern violates git_pathspec_v1 rules."""
    pass


FORBIDDEN_GLOB_CHARS = set("?[]{}!\\$`~()")
CATCH_ALL_PATTERNS = {"*", "**", "**/*", "*/*"}


def normalize_repo_path(path_str: str) -> str:
    """
    Validate and normalize a repository-relative path according to git_pathspec_v1.
    """
    if not path_str:
        raise PathSemanticsError("Empty path string is invalid")

    # Reject backslashes and control characters / NUL
    if "\\" in path_str:
        raise PathSemanticsError(f"Path contains backslash: {path_str!r}")
    if any(ord(c) < 32 or ord(c) == 127 for c in path_str):
        raise PathSemanticsError(f"Path contains control characters: {path_str!r}")

    # Unicode NFC normalization
    norm = unicodedata.normalize("NFC", path_str)

    # Rejections
    if norm.startswith("/") or norm.endswith("/"):
        raise PathSemanticsError(f"Absolute path or trailing slash rejected: {path_str!r}")

    parts = norm.split("/")
    for part in parts:
        if part == "" or part == "." or part == "..":
            raise PathSemanticsError(f"Invalid path segment {part!r} in {path_str!r}")

    return norm


def check_path_collisions(paths: Sequence[str]) -> None:
    """
    Check if any two paths collide after NFC normalization or case folding.
    """
    seen_nfc: dict[str, str] = {}
    seen_casefold: dict[str, str] = {}

    for p in paths:
        norm = normalize_repo_path(p)
        casefolded = norm.casefold()

        if norm in seen_nfc and seen_nfc[norm] != p:
            raise PathSemanticsError(f"NFC path collision between {p!r} and {seen_nfc[norm]!r}")
        seen_nfc[norm] = p

        if casefolded in seen_casefold and seen_casefold[casefolded] != p:
            raise PathSemanticsError(
                f"Case-folding path collision between {p!r} and {seen_casefold[casefolded]!r}"
            )
        seen_casefold[casefolded] = p


def pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """
    Compile a git_pathspec_v1 glob pattern to a Python regex.
    """
    if not pattern:
        raise PathSemanticsError("Empty pattern is invalid")

    norm_pattern = normalize_repo_path(pattern)

    if norm_pattern in CATCH_ALL_PATTERNS:
        raise PathSemanticsError(f"Forbidden catch-all pattern: {pattern!r}")

    # Check forbidden metacharacters
    for char in norm_pattern:
        if char in FORBIDDEN_GLOB_CHARS:
            raise PathSemanticsError(f"Forbidden character {char!r} in pattern {pattern!r}")

    # Check for Git pathspec magic or shell syntax
    if norm_pattern.startswith(":"):
        raise PathSemanticsError(f"Git pathspec magic forbidden in pattern: {pattern!r}")

    segments = norm_pattern.split("/")
    regex_parts: list[str] = []

    for i, seg in enumerate(segments):
        if seg == "**":
            if i == 0:
                if len(segments) == 1:
                    raise PathSemanticsError("Catch-all pattern ** is forbidden")
                regex_parts.append(r".*")
            elif i == len(segments) - 1:
                regex_parts.append(r"(?:/.*)?")
            else:
                regex_parts.append(r"(?:/.*)?")
        else:
            if i > 0 and segments[i - 1] != "**":
                regex_parts.append("/")

            subparts = seg.split("*")
            seg_regex = []
            for j, subpart in enumerate(subparts):
                seg_regex.append(re.escape(subpart))
                if j < len(subparts) - 1:
                    seg_regex.append(r"[^/]*")
            regex_parts.append("".join(seg_regex))

    regex_str = f"^{''.join(regex_parts)}$"
    return re.compile(regex_str)


def match_path_pattern(path: str, pattern: str) -> bool:
    """
    Check if a normalized path matches a git_pathspec_v1 pattern.
    """
    norm_path = normalize_repo_path(path)
    rx = pattern_to_regex(pattern)
    return bool(rx.match(norm_path))

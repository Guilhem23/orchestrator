#!/usr/bin/env python3
"""
Semantic Versioning (SemVer 2.0.0) Enforcement Script.
Validates version consistency across pyproject.toml, package __init__.py,
CHANGELOG.md, and Git release tags.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Standard library in Python 3.11+
import tomllib

SEMVER_REGEX = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def verify_semver(repo_dir: Path | None = None) -> int:
    root = Path(repo_dir).resolve() if repo_dir else Path.cwd().resolve()
    errors: list[str] = []

    # 1. Read pyproject.toml
    pyproject_file = root / "pyproject.toml"
    if not pyproject_file.is_file():
        print(f"❌ Error: pyproject.toml not found at {pyproject_file}", file=sys.stderr)
        return 1

    try:
        with open(pyproject_file, "rb") as f:
            pyproject_data = tomllib.load(f)
        pyproject_version = str(pyproject_data.get("project", {}).get("version", "")).strip()
    except Exception as exc:
        print(f"❌ Error parsing pyproject.toml: {exc}", file=sys.stderr)
        return 1

    if not pyproject_version:
        errors.append("`project.version` is missing or empty in pyproject.toml")
    elif not SEMVER_REGEX.match(pyproject_version):
        errors.append(
            f"`project.version` '{pyproject_version}' in pyproject.toml does not strictly adhere to Semantic Versioning (SemVer 2.0.0)."
        )

    # 2. Read slice_orchestrator/__init__.py
    init_file = root / "slice_orchestrator" / "__init__.py"
    init_version = ""
    if not init_file.is_file():
        errors.append(f"Package file not found: {init_file}")
    else:
        init_content = init_file.read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_content)
        if match:
            init_version = match.group(1).strip()
        else:
            errors.append("`__version__` declaration missing in slice_orchestrator/__init__.py")

    if init_version and pyproject_version and init_version != pyproject_version:
        errors.append(
            f"Version mismatch! pyproject.toml has '{pyproject_version}' but slice_orchestrator/__init__.py has '{init_version}'."
        )

    # 3. Read CHANGELOG.md
    changelog_file = root / "CHANGELOG.md"
    if not changelog_file.is_file():
        errors.append("CHANGELOG.md is missing. Every release must document changes.")
    else:
        changelog_content = changelog_file.read_text(encoding="utf-8")
        target_heading = f"## [{pyproject_version}]"
        if target_heading not in changelog_content:
            errors.append(
                f"CHANGELOG.md does not contain an entry for current version '{pyproject_version}' (expected '{target_heading}')."
            )

    # 4. Check Git Tag (if triggered by a release tag in CI)
    github_ref = os.environ.get("GITHUB_REF", "")
    if github_ref.startswith("refs/tags/"):
        tag_name = github_ref.removeprefix("refs/tags/").strip()
        expected_tag = f"v{pyproject_version}"
        if tag_name != expected_tag:
            errors.append(
                f"Release Git tag '{tag_name}' does not match expected version tag '{expected_tag}'."
            )

    # Report results
    step_summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if errors:
        print("\n❌ SemVer Verification FAILED:\n", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        if step_summary_path:
            with open(step_summary_path, "a", encoding="utf-8") as f:
                f.write("### ❌ Semantic Versioning Check Failed\n\n")
                for err in errors:
                    f.write(f"- 🚫 {err}\n")
        return 1

    print(f"✅ Semantic Versioning Verified Successfully!")
    print(f"  • Version: {pyproject_version}")
    print(f"  • pyproject.toml: {pyproject_version}")
    print(f"  • slice_orchestrator.__version__: {init_version}")
    print(f"  • CHANGELOG.md entry present: ## [{pyproject_version}]")
    if github_ref.startswith("refs/tags/"):
        print(f"  • Git Tag validated: {github_ref.removeprefix('refs/tags/')}")

    if step_summary_path:
        with open(step_summary_path, "a", encoding="utf-8") as f:
            f.write("### ✅ Semantic Versioning Check Passed\n\n")
            f.write(f"- **Version**: `{pyproject_version}` (valid SemVer 2.0.0)\n")
            f.write(f"- **Package Version**: `{init_version}` (synchronized)\n")
            f.write(f"- **Changelog**: Documented in `CHANGELOG.md`\n")

    return 0


if __name__ == "__main__":
    sys.exit(verify_semver())

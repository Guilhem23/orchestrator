"""
Git Manager, Candidate Capture, Scope Manifest Validator, and Atomic Commit Manager for Method v4.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

from slice_orchestrator.path_semantics import (
    PathSemanticsError,
    check_path_collisions,
    match_path_pattern,
    normalize_repo_path,
)


class GitManagerError(ValueError):
    """Raised when Git operations or scope validation fail."""
    pass


def run_git_cmd(
    args: list[str],
    repo_dir: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> str:
    """
    Execute a Git command safely with clean environment (hooks disabled, custom index when needed).
    """
    cmd_env = dict(os.environ)
    if env:
        cmd_env.update(env)

    cmd_env["GIT_CONFIG_NOSYSTEM"] = "1"
    cmd_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    cmd = ["git", "-C", str(repo_dir)] + args

    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=cmd_env,
    )
    if check and res.returncode != 0:
        raise GitManagerError(f"Git command failed: {' '.join(cmd)}\nStderr: {res.stderr.strip()}")
    return res.stdout.strip()


def get_git_object_format(repo_dir: Path) -> str:
    try:
        fmt = run_git_cmd(["rev-parse", "--show-object-format"], repo_dir, check=False)
        if fmt and fmt in ("sha1", "sha256"):
            return fmt
    except Exception:
        pass
    return "sha1"


def get_head_commit_oid(repo_dir: Path) -> str:
    fmt = get_git_object_format(repo_dir)
    raw = run_git_cmd(["rev-parse", "HEAD"], repo_dir)
    return f"{fmt}:{raw}"


class ScopeManifestValidator:
    """
    Validates complete base-to-candidate diff against scope manifest and protected files policy.
    """

    def __init__(self, scope_manifest: dict[str, Any], protected_files_policy: dict[str, Any]):
        self.scope_manifest = scope_manifest
        self.protected_files_policy = protected_files_policy

        self.allowed_rules = scope_manifest.get("allow_paths", [])
        self.protected_classes = protected_files_policy.get("workspace_classes", {})

    def check_diff(self, diff_entries: list[dict[str, str]]) -> None:
        """
        diff_entries: list of dicts with 'status' (A, M, D, R, etc.), 'path' (repo relative), optional 'new_path'.
        """
        changed_paths = [e["path"] for e in diff_entries]
        for e in diff_entries:
            if "new_path" in e and e["new_path"]:
                changed_paths.append(e["new_path"])

        try:
            check_path_collisions(changed_paths)
        except PathSemanticsError as exc:
            raise GitManagerError(f"Scope validation failed due to path collision: {exc}") from exc

        for entry in diff_entries:
            path = normalize_repo_path(entry["path"])
            status = entry["status"]

            # 1. Check Protected Files Policy (Deny rules always win)
            for class_name, class_def in self.protected_classes.items():
                patterns = class_def.get("patterns", [])
                for pat in patterns:
                    try:
                        if match_path_pattern(path, pat):
                            perms = class_def.get("permissions", {}).get("IMPLEMENTER", [])
                            if not perms:
                                raise GitManagerError(
                                    f"Protected path modification denied: {path!r} matches protected class {class_name}"
                                )
                            if status == "A" and "add" not in perms:
                                raise GitManagerError(f"Protected path add denied: {path!r}")
                            if status == "M" and "modify" not in perms:
                                raise GitManagerError(f"Protected path modify denied: {path!r}")
                            if status == "D" and "delete" not in perms:
                                raise GitManagerError(f"Protected path delete denied: {path!r}")
                    except PathSemanticsError:
                        pass

            # 2. Check Scope Manifest Match
            matched = False
            for rule in self.allowed_rules:
                pat = rule.get("pattern")
                allowed_ops = rule.get("allowed_operations", ["add", "modify", "delete", "rename", "mode_change"])
                if pat:
                    try:
                        if match_path_pattern(path, pat):
                            op_map = {"A": "add", "M": "modify", "D": "delete", "R": "rename"}
                            op_name = op_map.get(status, "modify")
                            if op_name not in allowed_ops:
                                raise GitManagerError(
                                    f"Operation {op_name} on {path!r} not permitted by scope manifest rule {pat!r}"
                                )
                            matched = True
                            break
                    except PathSemanticsError:
                        pass

            if not matched:
                raise GitManagerError(f"Path modification {path!r} (status {status}) is not authorized by scope manifest")


CONTROL_RESIDUE_DIR_NAMES = frozenset({
    ".orchestrator_slice",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".eggs",
    ".hypothesis",
    "node_modules",
})
CONTROL_RESIDUE_SUFFIXES = (".pyc", ".pyo", ".pyd")


def is_control_residue_path(rel_path: str, control_home_rel: str | None = None) -> bool:
    """
    Return True when a repo-relative path is orchestrator/tool residue and
    must not participate in workspace-revision identity.
    """
    normalized = rel_path.replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    if control_home_rel:
        home = control_home_rel.replace("\\", "/").lstrip("./").rstrip("/")
        if normalized == home or normalized.startswith(home + "/"):
            return True
    parts = [p for p in normalized.split("/") if p]
    if any(part in CONTROL_RESIDUE_DIR_NAMES for part in parts):
        return True
    if normalized.endswith(CONTROL_RESIDUE_SUFFIXES):
        return True
    return False


class CandidateTreeBuilder:
    """
    Captures candidate tree OID using a controller-private Git index.
    """

    def __init__(self, repo_dir: Path, control_home: Path):
        self.repo_dir = repo_dir.resolve()
        self.control_home = control_home.resolve()

    def _control_home_rel(self) -> str | None:
        try:
            return str(self.control_home.relative_to(self.repo_dir)).replace("\\", "/")
        except ValueError:
            return None

    def capture_candidate_tree(self, base_commit_oid: str) -> str:
        """
        Build candidate tree in a private index and return candidate_tree_oid.
        Control-home files and tool residue are excluded so recapture of
        unchanged reviewed content is stable.
        base_commit_oid format: 'sha1:<hex>' or '<hex>'.
        """
        raw_base = base_commit_oid.split(":")[-1]
        self.control_home.mkdir(parents=True, exist_ok=True)
        (self.control_home / "locks").mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(dir=self.control_home / "locks", delete=False) as tmp_idx:
            index_file = tmp_idx.name

        try:
            env = {"GIT_INDEX_FILE": index_file}

            # 1. Read base commit tree into private index
            run_git_cmd(["read-tree", raw_base], self.repo_dir, env=env)

            # 2. Add/update all worktree changes into private index
            run_git_cmd(["add", "-A"], self.repo_dir, env=env)

            # 3. Drop control-home and tool residue so they cannot drift the digest
            control_rel = self._control_home_rel()
            staged = run_git_cmd(["ls-files"], self.repo_dir, env=env, check=False)
            for path in staged.splitlines():
                if is_control_residue_path(path, control_rel):
                    run_git_cmd(
                        ["rm", "--cached", "-f", "--ignore-unmatch", "--", path],
                        self.repo_dir,
                        env=env,
                        check=False,
                    )

            # 4. Write tree from private index
            raw_tree_oid = run_git_cmd(["write-tree"], self.repo_dir, env=env)
            fmt = get_git_object_format(self.repo_dir)
            return f"{fmt}:{raw_tree_oid}"

        finally:
            if os.path.exists(index_file):
                os.remove(index_file)

    def compute_base_to_candidate_diff(self, base_commit_oid: str, candidate_tree_oid: str) -> list[dict[str, str]]:
        """
        Compute diff between base commit and candidate tree using git diff-tree.
        """
        raw_base = base_commit_oid.split(":")[-1]
        raw_candidate = candidate_tree_oid.split(":")[-1]

        diff_out = run_git_cmd(
            ["diff-tree", "-r", "-z", "--name-status", raw_base, raw_candidate],
            self.repo_dir,
        )

        parts = diff_out.split("\x00") if diff_out else []
        diff_entries: list[dict[str, str]] = []
        i = 0
        while i < len(parts):
            if not parts[i]:
                i += 1
                continue
            status_raw = parts[i]
            status_code = status_raw[0]
            i += 1
            if i < len(parts):
                path = parts[i]
                i += 1
                entry = {"status": status_code, "path": path}
                if status_code in ("R", "C") and i < len(parts):
                    entry["new_path"] = parts[i]
                    i += 1
                diff_entries.append(entry)

        return diff_entries


def compute_workspace_revision_digest(
    project_id: str,
    git_object_format: str,
    base_commit_oid: str,
    candidate_tree_oid: str,
    plan_revision: int,
    plan_digest: str,
    scope_manifest_digest: str,
    required_test_plan_digest: str,
    policy_bundle_digest: str,
) -> str:
    """
    Compute domain-separated SHA-256 workspace_revision_digest.
    Domain: slice-orchestrator-v4/revision/v1
    """
    hasher = hashlib.sha256()
    hasher.update(b"slice-orchestrator-v4/revision/v1\n")
    items = [
        project_id,
        git_object_format,
        base_commit_oid,
        candidate_tree_oid,
        str(plan_revision),
        plan_digest,
        scope_manifest_digest,
        required_test_plan_digest,
        policy_bundle_digest,
    ]
    for item in items:
        hasher.update(item.encode("utf-8") + b"\n")
    return hasher.hexdigest()


def compute_evidence_set_digest(receipt_digests: Sequence[str]) -> str:
    """
    Compute domain-separated SHA-256 evidence_set_digest.
    Domain: slice-orchestrator-v4/evidence-set/v1
    """
    hasher = hashlib.sha256()
    hasher.update(b"slice-orchestrator-v4/evidence-set/v1\n")
    sorted_receipts = sorted(receipt_digests)
    for r in sorted_receipts:
        hasher.update(r.encode("utf-8") + b"\n")
    return hasher.hexdigest()


def compute_approved_revision_digest(workspace_revision_digest: str, evidence_set_digest: str) -> str:
    """
    Compute domain-separated SHA-256 approved_revision_digest.
    Domain: slice-orchestrator-v4/approved-revision/v1
    """
    hasher = hashlib.sha256()
    hasher.update(b"slice-orchestrator-v4/approved-revision/v1\n")
    hasher.update(workspace_revision_digest.encode("utf-8") + b"\n")
    hasher.update(evidence_set_digest.encode("utf-8") + b"\n")
    return hasher.hexdigest()


class AtomicCommitManager:
    """
    Manages final commit creation and atomic ref compare-and-swap according to Method v4.
    """

    def __init__(self, repo_dir: Path, control_home: Path):
        self.repo_dir = repo_dir.resolve()
        self.control_home = control_home.resolve()

    def create_commit_and_update_ref(
        self,
        accepted_candidate_tree_oid: str,
        expected_parent_commit_oid: str,
        commit_message: str,
        target_ref: str = "refs/heads/main",
    ) -> str:
        """
        1. Populate private commit index only from accepted immutable candidate tree objects.
        2. Verify write-tree == accepted_candidate_tree_oid.
        3. Create commit object (git commit-tree).
        4. Compare-and-swap authoritative ref (git update-ref).
        Returns created commit OID (fmt:hex).
        """
        raw_tree = accepted_candidate_tree_oid.split(":")[-1]
        raw_parent = expected_parent_commit_oid.split(":")[-1]
        fmt = get_git_object_format(self.repo_dir)

        with tempfile.NamedTemporaryFile(dir=self.control_home / "locks", delete=False) as tmp_idx:
            index_file = tmp_idx.name

        try:
            env = {"GIT_INDEX_FILE": index_file}

            # 1. Populate private index from accepted immutable tree ONLY
            run_git_cmd(["read-tree", raw_tree], self.repo_dir, env=env)

            # 2. Verify write-tree
            staged_tree = run_git_cmd(["write-tree"], self.repo_dir, env=env)
            if staged_tree != raw_tree:
                raise GitManagerError(
                    f"Staged tree mismatch! Expected accepted tree {raw_tree}, got staged tree {staged_tree}"
                )

            # 3. Create commit object
            commit_cmd = ["commit-tree", raw_tree, "-p", raw_parent, "-m", commit_message]
            raw_commit_oid = run_git_cmd(commit_cmd, self.repo_dir, env=env)

            # Verify created commit tree
            created_tree = run_git_cmd(["rev-parse", f"{raw_commit_oid}^{{tree}}"], self.repo_dir)
            if created_tree != raw_tree:
                raise GitManagerError(
                    f"Created commit tree mismatch! Expected {raw_tree}, got {created_tree}"
                )

            # 4. Compare-and-swap ref atomically
            run_git_cmd(["update-ref", target_ref, raw_commit_oid, raw_parent], self.repo_dir, env=env)

            return f"{fmt}:{raw_commit_oid}"

        finally:
            if os.path.exists(index_file):
                os.remove(index_file)

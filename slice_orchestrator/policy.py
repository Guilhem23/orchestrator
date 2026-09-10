"""
Policy bundle verification and schema validator for Method v4.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

from slice_orchestrator.path_semantics import normalize_repo_path


BUNDLE_PREFIX = b"slice-orchestrator-v4/policy-bundle/v1\x00"


class PolicyError(ValueError):
    """Raised when policy verification fails."""
    pass


def compute_policy_bundle_digest_from_files(files_map: dict[str, bytes]) -> str:
    """
    Compute bundle digest according to sorted_relative_path_nul_length_bytes_v1.
    files_map: dict mapping relative path string to content bytes.
    """
    hasher = hashlib.sha256()
    hasher.update(BUNDLE_PREFIX)

    sorted_paths = sorted(files_map.keys(), key=lambda p: normalize_repo_path(p).encode("utf-8"))

    for rel_path in sorted_paths:
        norm_path = normalize_repo_path(rel_path)
        path_bytes = norm_path.encode("utf-8")
        content_bytes = files_map[rel_path]

        path_len = struct.pack(">Q", len(path_bytes))
        content_len = struct.pack(">Q", len(content_bytes))

        hasher.update(path_len)
        hasher.update(path_bytes)
        hasher.update(content_len)
        hasher.update(content_bytes)

    return hasher.hexdigest()


def compute_policy_bundle_digest(bundle_dir: Path) -> str:
    """
    Compute the policy bundle digest for a given policy bundle directory.
    Reads slice-policy.yaml to find required_files.
    """
    slice_policy_path = bundle_dir / "slice-policy.yaml"
    if not slice_policy_path.is_file():
        raise PolicyError(f"Missing slice-policy.yaml in policy bundle directory {bundle_dir}")

    try:
        policy_data = yaml.safe_load(slice_policy_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PolicyError(f"Failed to parse slice-policy.yaml: {exc}") from exc

    required_files = policy_data.get("policy_bundle", {}).get("required_files", [])
    if not required_files:
        required_files = [
            f.relative_to(bundle_dir).as_posix()
            for f in sorted(bundle_dir.glob("*"))
            if f.is_file() and f.suffix in (".yaml", ".yml", ".json")
        ]
    if not required_files:
        raise PolicyError("slice-policy.yaml specifies no required_files and no policy files found")

    files_map: dict[str, bytes] = {}
    for req_rel_path in required_files:
        full_path = bundle_dir / req_rel_path
        if not full_path.is_file():
            raise PolicyError(f"Required policy file missing: {req_rel_path}")
        files_map[req_rel_path] = full_path.read_bytes()

    return compute_policy_bundle_digest_from_files(files_map)


class PolicyBundle:
    """
    Loads, validates, and holds an installed Policy Bundle.
    """

    def __init__(self, bundle_dir: Path, pinned_digest: str | None = None):
        self.bundle_dir = bundle_dir.resolve()
        if not self.bundle_dir.is_dir():
            raise PolicyError(f"Policy bundle directory does not exist: {self.bundle_dir}")

        self.computed_digest = compute_policy_bundle_digest(self.bundle_dir)

        if pinned_digest is not None:
            if self.computed_digest != pinned_digest:
                raise PolicyError(
                    f"Policy bundle digest mismatch! Computed: {self.computed_digest}, Pinned: {pinned_digest}"
                )

        self.slice_policy = yaml.safe_load((self.bundle_dir / "slice-policy.yaml").read_text(encoding="utf-8"))
        self.transitions = yaml.safe_load((self.bundle_dir / "transitions.yaml").read_text(encoding="utf-8"))
        self.protected_files = yaml.safe_load((self.bundle_dir / "protected-files.yaml").read_text(encoding="utf-8"))

        # Pre-load schemas
        self.schemas: dict[str, dict[str, Any]] = {}
        for schema_file in self.bundle_dir.glob("*.schema.json"):
            try:
                schema_json = json.loads(schema_file.read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema_json)
                self.schemas[schema_file.name] = schema_json
            except Exception as exc:
                raise PolicyError(f"Invalid schema file {schema_file.name}: {exc}") from exc

        # Build schema registry for local $ref resolution
        self.registry = Registry()
        for filename, schema_json in self.schemas.items():
            resource = Resource.from_contents(schema_json)
            schema_id = schema_json.get("$id")
            if schema_id:
                self.registry = self.registry.with_resource(schema_id, resource)
                if "/" in schema_id:
                    base_prefix = schema_id.rsplit("/", 1)[0]
                    self.registry = self.registry.with_resource(f"{base_prefix}/{filename}", resource)
            self.registry = self.registry.with_resource(filename, resource)

        self.validators: dict[str, Draft202012Validator] = {}
        for filename, schema_json in self.schemas.items():
            self.validators[filename] = Draft202012Validator(schema_json, registry=self.registry)

    def validate_schema(self, schema_filename: str, data: Any) -> None:
        """
        Validate data against a named schema in the policy bundle.
        """
        if schema_filename not in self.validators:
            raise PolicyError(f"Schema {schema_filename} not found in policy bundle")
        try:
            self.validators[schema_filename].validate(data)
        except ValidationError as exc:
            raise PolicyError(f"Schema validation failed for {schema_filename}: {exc.message}") from exc

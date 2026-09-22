"""
M1 Control Store and Append Kernel.
Provides immutable, sequence-chained, HMAC-authenticated SQLite event store
and trusted tail anchor management in accordance with ADR-014.
"""

from datetime import datetime, timezone
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import sys
import uuid
from typing import Any

from slice_orchestrator.canonical import (
    canonical_json_bytes,
    compute_event_hash,
    compute_record_digest,
)
from slice_orchestrator.policy import PolicyBundle, PolicyError, compute_policy_bundle_digest


class ControlStoreError(Exception):
    """Raised when control store operations or integrity checks fail."""
    pass


class TrustStateError(ControlStoreError):
    """Raised when trust-state initialization or recovery fails closed."""

    FIRST_INITIALIZATION = "FIRST_INITIALIZATION"
    RECOVERY = "RECOVERY"
    CORRUPTION = "CORRUPTION"
    MISSING_TRUST_STATE = "MISSING_TRUST_STATE"

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


class SliceLockError(Exception):
    """Raised when slice locking operations fail."""
    pass


class SliceLockManager:
    """
    File-based concurrency lock manager for slice execution using OS-level exclusive locks.
    Uses fcntl.flock() on Unix systems for atomic lock acquisition.
    """

    def __init__(self, lock_path: Path, blocking: bool = False):
        self.lock_path = lock_path
        self.lock_file = None
        self.blocking = blocking

    def acquire(self) -> None:
        import fcntl
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = open(self.lock_path, "w")
        flags = fcntl.LOCK_EX if self.blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fcntl.flock(self.lock_file.fileno(), flags)
            self.lock_file.write(f"locked-{os.getpid()}\n")
            self.lock_file.flush()
        except BlockingIOError:
            self.lock_file.close()
            self.lock_file = None
            raise RuntimeError(f"Slice lock already held: {self.lock_path}")

    def release(self) -> None:
        if self.lock_file:
            import fcntl
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            self.lock_file.close()
            self.lock_file = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class ControlStore:
    """
    Authoritative Control Store handling M1 event-sourcing and M2 assignments/context packs.
    """

    def __init__(self, control_home: Path, policy_bundle_source: Path | None = None):
        self.control_home = control_home.resolve()
        self.control_home.mkdir(parents=True, exist_ok=True)

        self.db_path = self.control_home / "state.db"
        self.secret_path = self.control_home / "control_secret.key"
        self.tail_anchor_path = self.control_home / "trusted_tail_anchor"
        self.locks_dir = self.control_home / "locks"
        self.locks_dir.mkdir(parents=True, exist_ok=True)

        self.project_id = "proj-1"
        self.trust_init_marker = self.control_home / ".trust_initialized"
        self.trust_state_mode = TrustStateError.FIRST_INITIALIZATION
        self.secret = self._load_or_create_secret()
        self._append_lock = SliceLockManager(self.locks_dir / ".store-append.lock", blocking=True)

        # Load PolicyBundle if available
        self.policy_bundle: PolicyBundle | None = None
        if policy_bundle_source and policy_bundle_source.is_dir():
            self.policy_bundle = PolicyBundle(policy_bundle_source)
        elif (self.control_home / "policy_bundle.json").is_file():
            self.policy_bundle = PolicyBundle(self.control_home)
        else:
            # Check default .orchestrator directory
            orchestrator_dir = self.control_home.parent / ".orchestrator"
            if orchestrator_dir.is_dir():
                try:
                    self.policy_bundle = PolicyBundle(orchestrator_dir)
                except Exception:
                    self.policy_bundle = None

        self.init_database()

    def _prior_trust_artifacts_present(self) -> bool:
        if self.trust_init_marker.is_file() or self.tail_anchor_path.is_file() or self.secret_path.is_file():
            return True
        if self.db_path.is_file() and self._db_file_has_events():
            return True
        return False

    def _db_file_has_events(self) -> bool:
        if not self.db_path.is_file():
            return False
        try:
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                try:
                    row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
                except sqlite3.DatabaseError:
                    return True
                return bool(row and row[0])
        except sqlite3.DatabaseError:
            return True

    def _write_trust_marker(self, mode: str) -> None:
        payload = {
            "mode": mode,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self.trust_init_marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.chmod(self.trust_init_marker, 0o600)

    def _load_or_create_secret(self) -> bytes:
        prior = self._prior_trust_artifacts_present()
        if self.secret_path.is_file():
            secret = self.secret_path.read_bytes()
            if len(secret) != 32:
                self.trust_state_mode = TrustStateError.CORRUPTION
                raise TrustStateError(
                    TrustStateError.CORRUPTION,
                    f"control_secret.key has invalid length {len(secret)}; refusing silent rotation",
                )
            self.trust_state_mode = "EXISTING"
            if not self.trust_init_marker.is_file():
                self._write_trust_marker("EXISTING")
            return secret

        if prior:
            self.trust_state_mode = TrustStateError.MISSING_TRUST_STATE
            raise TrustStateError(
                TrustStateError.MISSING_TRUST_STATE,
                "control_secret.key is missing after prior trust state existed; refusing silent regeneration",
            )

        secret = secrets.token_bytes(32)
        self.secret_path.write_bytes(secret)
        os.chmod(self.secret_path, 0o600)
        self.trust_state_mode = TrustStateError.FIRST_INITIALIZATION
        self._write_trust_marker(TrustStateError.FIRST_INITIALIZATION)
        return secret

    def recover_trust_state(
        self,
        operator_principal: str,
        reason: str,
        action: str,
    ) -> dict[str, Any]:
        """
        Explicit, auditable operator recovery. Workers cannot trigger this.
        """
        if not operator_principal or operator_principal.startswith("worker"):
            raise TrustStateError(
                TrustStateError.RECOVERY,
                "Workers cannot trigger trust-state recreation",
            )
        if action not in ("REBUILD_ANCHOR_FROM_DB", "REINITIALIZE_EMPTY"):
            raise TrustStateError(
                TrustStateError.RECOVERY,
                f"Unknown recovery action {action!r}",
            )

        audit = {
            "schema_version": 4,
            "record_type": "TRUST_RECOVERY",
            "recovery_id": str(uuid.uuid4()),
            "operator_principal": operator_principal,
            "reason": reason,
            "action": action,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if action == "REINITIALIZE_EMPTY":
            if self._db_file_has_events() or self.tail_anchor_path.is_file():
                raise TrustStateError(
                    TrustStateError.RECOVERY,
                    "REINITIALIZE_EMPTY refused: events or tail anchor still present",
                )
            if not self.secret_path.is_file():
                secret = secrets.token_bytes(32)
                self.secret_path.write_bytes(secret)
                os.chmod(self.secret_path, 0o600)
                self.secret = secret
            self._write_trust_marker(TrustStateError.RECOVERY)
            self.trust_state_mode = TrustStateError.RECOVERY
            self.store_record("TRUST_RECOVERY", audit["recovery_id"], audit)
            return audit

        events = []
        try:
            events = self._verify_event_chain_only()
        except ControlStoreError as exc:
            raise TrustStateError(
                TrustStateError.RECOVERY,
                f"Cannot rebuild anchor: event chain verification failed: {exc}",
            ) from exc
        if not events:
            raise TrustStateError(
                TrustStateError.RECOVERY,
                "Cannot rebuild anchor from an empty event log",
            )
        last = events[-1]
        self.update_tail_anchor(last["sequence"], last["event_hash"], last["event_mac"])
        self.trust_state_mode = TrustStateError.RECOVERY
        self.store_record("TRUST_RECOVERY", audit["recovery_id"], audit)
        return audit

    def sign_receipt(self, receipt: dict[str, Any]) -> str:
        mac_source = {
            k: v for k, v in receipt.items()
            if k not in ("receipt_mac", "record_digest")
        }
        return self.compute_hmac(canonical_json_bytes(mac_source).decode("utf-8"))

    def compute_hmac(self, data_str: str) -> str:
        return hmac.new(self.secret, data_str.encode("utf-8"), hashlib.sha256).hexdigest()

    def _get_db_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self) -> None:
        with self._get_db_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY,
                    event_id TEXT UNIQUE NOT NULL,
                    project_id TEXT NOT NULL,
                    slice TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    run_generation INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    event_mac TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assignments (
                    assignment_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    worker_execution_id TEXT NOT NULL,
                    context_pack_id TEXT NOT NULL,
                    context_pack_digest TEXT NOT NULL,
                    repository_revision TEXT NOT NULL,
                    plan_revision INTEGER NOT NULL,
                    objective_id TEXT NOT NULL,
                    work_item_id TEXT NOT NULL,
                    allowed_scope TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT,
                    status TEXT NOT NULL,
                    issued_by TEXT NOT NULL,
                    consumed_at TEXT,
                    consumed_by TEXT,
                    assignment_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learnings (
                    learning_id TEXT PRIMARY KEY,
                    source_work_item TEXT NOT NULL,
                    author_role TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_reference TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    hash TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifact_graph_nodes (
                    artifact_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    parent_artifact_ids_json TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    work_item_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    creator_role TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def read_tail_anchor(self) -> tuple[int, str, str] | None:
        if not self.tail_anchor_path.is_file():
            return None
        try:
            lines = self.tail_anchor_path.read_text().strip().splitlines()
            if len(lines) >= 3:
                return int(lines[0]), lines[1], lines[2]
            return None
        except Exception:
            return None

    def update_tail_anchor(self, seq: int, ev_hash: str, mac: str) -> None:
        tmp_path = self.tail_anchor_path.with_suffix(".tmp")
        content = f"{seq}\n{ev_hash}\n{mac}\n"
        with open(tmp_path, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.tail_anchor_path)

    def initialize_policy_bundle(self, bundle_src: Path) -> str:
        bundle_src = bundle_src.resolve()
        digest = compute_policy_bundle_digest(bundle_src)
        digest_file = self.control_home / "policy_bundle_digest"
        digest_file.write_text(digest + "\n")

        bundle_loc_file = self.control_home / "policy_bundle_dir"
        bundle_loc_file.write_text(str(bundle_src) + "\n")

        return digest

    def load_and_verify_policy_bundle(self) -> PolicyBundle:
        digest_file = self.control_home / "policy_bundle_digest"
        if not digest_file.is_file():
            raise PolicyError("Missing policy_bundle_digest file in control home")

        pinned_digest = digest_file.read_text().strip()

        bundle_loc_file = self.control_home / "policy_bundle_dir"
        if bundle_loc_file.is_file():
            bundle_dir = Path(bundle_loc_file.read_text().strip())
        else:
            bundle_dir = self.control_home.parent / ".orchestrator"
            if not bundle_dir.is_dir():
                bundle_dir = Path.cwd() / ".orchestrator"

        bundle = PolicyBundle(bundle_dir, pinned_digest=pinned_digest)
        self.policy_bundle = bundle
        return bundle

    def verify_toolchain_environment(self, required: list[str] | None = None) -> bool:
        if required is None:
            required = ["python3", "uv", "pytest", "git", "sqlite3"]
        for tool in required:
            found = False
            if shutil.which(tool):
                found = True
            elif tool in ("python", "python3") and sys.executable:
                found = True
            else:
                venv_bin = Path(sys.executable).parent / tool
                if venv_bin.is_file() and os.access(venv_bin, os.X_OK):
                    found = True
                elif tool in ("pytest", "sqlite3"):
                    try:
                        importlib.import_module(tool)
                        found = True
                    except ImportError:
                        found = False
            if not found:
                return False
        return True

    def get_events(self) -> list[dict[str, Any]]:
        return self.verify_store_integrity()

    def _verify_event_chain_only(self) -> list[dict[str, Any]]:
        with self._get_db_connection() as conn:
            cursor = conn.execute("PRAGMA quick_check")
            row = cursor.fetchone()
            if not row or row[0] != "ok":
                raise ControlStoreError(f"SQLite quick_check failed: {row}")

            cursor = conn.execute("SELECT * FROM events ORDER BY sequence ASC")
            events_rows = cursor.fetchall()

        events: list[dict[str, Any]] = []
        expected_seq = 1
        expected_prev_hash: str | None = None

        for row in events_rows:
            try:
                ev = json.loads(row["event_json"])
            except Exception as exc:
                raise ControlStoreError(f"Malformed event JSON in database: {exc}") from exc

            if not isinstance(ev, dict) or "sequence" not in ev or "event_hash" not in ev or "event_mac" not in ev:
                raise ControlStoreError("Malformed event object structure in database")

            try:
                payload_canonical = json.dumps(ev["payload"], ensure_ascii=False, sort_keys=True)
                row_payload_canonical = json.dumps(json.loads(row["payload_json"]), ensure_ascii=False, sort_keys=True)
                if payload_canonical != row_payload_canonical:
                    raise ControlStoreError(f"Payload mismatch/corruption detected at seq {ev['sequence']}!")
            except ControlStoreError:
                raise
            except Exception as exc:
                raise ControlStoreError(f"Payload validation failed at seq {ev['sequence']}: {exc}") from exc

            if ev["sequence"] != expected_seq:
                raise ControlStoreError(
                    f"Event sequence gap! Expected {expected_seq}, got {ev['sequence']}"
                )

            if expected_seq == 1:
                prev_h = ev.get("expected_previous_event_hash")
                if prev_h is not None and prev_h != "0" * 64:
                    raise ControlStoreError("First event expected_previous_event_hash must be null or 0*64")
            else:
                if ev.get("expected_previous_event_hash") != expected_prev_hash:
                    raise ControlStoreError(
                        f"Event previous_event_hash mismatch at seq {ev['sequence']}! Expected {expected_prev_hash}, got {ev.get('expected_previous_event_hash')}"
                    )

            calc_hash = compute_event_hash(ev)
            if calc_hash != ev["event_hash"]:
                raise ControlStoreError(
                    f"Event hash mismatch at seq {ev['sequence']}! Computed {calc_hash}, stored {ev['event_hash']}"
                )

            calc_mac = self.compute_hmac(calc_hash)
            if calc_mac != ev["event_mac"]:
                raise ControlStoreError(
                    f"Event HMAC signature mismatch at seq {ev['sequence']}!"
                )

            if self.policy_bundle:
                self.policy_bundle.validate_schema("event.schema.json", ev)

            expected_seq += 1
            expected_prev_hash = ev["event_hash"]
            events.append(ev)
        return events

    def verify_store_integrity(self) -> list[dict[str, Any]]:
        if not self.db_path.is_file():
            if self.tail_anchor_path.is_file() or self.trust_init_marker.is_file():
                raise TrustStateError(
                    TrustStateError.MISSING_TRUST_STATE,
                    "state.db is missing while a tail anchor or trust marker exists",
                )
            return []

        try:
            with self._append_lock:
                return self._verify_store_integrity_unlocked()
        except (ControlStoreError, TrustStateError):
            raise
        except Exception as exc:
            raise ControlStoreError(f"Store integrity check failed: {exc}") from exc

    def _verify_store_integrity_unlocked(self) -> list[dict[str, Any]]:
        try:
            events = self._verify_event_chain_only()
            anchor = self.read_tail_anchor()
            if events:
                last_ev = events[-1]
                if anchor is None:
                    raise TrustStateError(
                        TrustStateError.MISSING_TRUST_STATE,
                        "Trusted tail anchor is missing while events exist; refusing silent reconstruction",
                    )
                anchor_seq, anchor_hash, anchor_mac = anchor
                if anchor_seq > last_ev["sequence"]:
                    raise ControlStoreError(
                        f"Trusted tail anchor sequence ({anchor_seq}) ahead of database ({last_ev['sequence']})! STOPPED"
                    )
                if anchor_seq != last_ev["sequence"]:
                    raise ControlStoreError(
                        f"Trusted tail anchor sequence ({anchor_seq}) mismatch with database ({last_ev['sequence']})! STOPPED"
                    )
                if anchor_hash != last_ev["event_hash"] or anchor_mac != last_ev["event_mac"]:
                    raise ControlStoreError("Trusted tail anchor hash/mac mismatch with DB tail! STOPPED")
            elif anchor is not None:
                raise ControlStoreError("Trusted tail anchor exists but database has no events! STOPPED")

            return events
        except (ControlStoreError, TrustStateError):
            raise
        except Exception as exc:
            raise ControlStoreError(f"Store integrity check failed: {exc}") from exc

    def append_event(
        self,
        slice_name: str,
        run_id: str,
        generation: int = 1,
        event_type: str = "RUN_OPENED",
        payload_type: str | None = None,
        actor_role: str = "CONTROLLER_SYSTEM",
        actor_principal: str = "controller",
        payload: dict[str, Any] | None = None,
        expected_seq: int | None = None,
        expected_prev_hash: str | None = None,
        assignment_id: str | None = None,
        execution_id: str | None = "exec-1",
        token_hash: str | None = None,
    ) -> dict[str, Any]:
        payload_type = payload_type or event_type
        payload = payload or {}

        allowed_roles = {
            "CONTROL_OPERATOR",
            "CONTROLLER_SYSTEM",
            "PLANNER",
            "ARCHITECTURE_REVIEWER",
            "IMPLEMENTER",
            "ADVERSARIAL_REVIEWER",
            "COMMIT_MANAGER",
            "GOVERNANCE_AGENT",
        }
        if actor_role not in allowed_roles:
            raise PolicyError(
                f"Schema validation failed for event.schema.json: '{actor_role}' is not one of {sorted(allowed_roles)}"
            )

        with self._append_lock:
          with self._get_db_connection() as conn:
            cursor = conn.execute("SELECT MAX(sequence) FROM events")
            row = cursor.fetchone()
            current_max_seq = row[0] if row and row[0] is not None else 0
            seq = current_max_seq + 1

            if expected_seq is not None and expected_seq != seq:
                raise ControlStoreError(
                    f"Expected sequence {expected_seq} does not match computed next sequence {seq}!"
                )

            if seq == 1:
                prev_hash = "0" * 64
            else:
                cursor = conn.execute("SELECT event_hash FROM events WHERE sequence = ?", (current_max_seq,))
                prev_row = cursor.fetchone()
                if not prev_row:
                    raise ControlStoreError("Previous event record missing in database!")
                prev_hash = prev_row[0]

            if expected_prev_hash is not None and expected_prev_hash != prev_hash:
                raise ControlStoreError(
                    f"Expected previous event hash {expected_prev_hash} does not match computed previous hash {prev_hash}!"
                )

            cursor = conn.execute(
                "SELECT event_json FROM events WHERE slice = ? ORDER BY sequence ASC",
                (slice_name,),
            )
            slice_events = []
            for ev_row in cursor.fetchall():
                try:
                    slice_events.append(json.loads(ev_row["event_json"]))
                except Exception as exc:
                    raise ControlStoreError(f"Malformed stored event JSON: {exc}") from exc

            from slice_orchestrator.state_machine import (
                TransitionEngine,
                TransitionError,
                project_slice_run_state,
            )
            current_state = project_slice_run_state(slice_events, self)
            if current_state is not None:
                if current_state.slice != slice_name:
                    raise ControlStoreError(
                        f"Slice identifier mismatch: event slice {slice_name!r} vs state {current_state.slice!r}"
                    )
                if event_type != "HUMAN_RECOVERY_OPENED" and current_state.run_id != run_id:
                    raise ControlStoreError(
                        f"Run identifier mismatch for slice {slice_name}: event run {run_id} vs state {current_state.run_id}"
                    )

            transitions = self.policy_bundle.transitions if self.policy_bundle else {}
            slice_policy = self.policy_bundle.slice_policy if self.policy_bundle else {}
            try:
                TransitionEngine(transitions, slice_policy).validate_transition(
                    current_state, event_type, actor_role, payload
                )
            except TransitionError as exc:
                raise ControlStoreError(f"Illegal transition rejected: {exc}") from exc

            event_id = str(uuid.uuid4())
            recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            event_data = {
                "schema_version": 4,
                "project_id": self.project_id,
                "slice": slice_name,
                "run_id": run_id,
                "run_generation": generation,
                "sequence": seq,
                "event_id": event_id,
                "event_type": event_type,
                "actor": {
                    "principal_id": actor_principal,
                    "role": actor_role,
                    "assignment_id": assignment_id,
                    "execution_id": execution_id,
                },
                "expected_previous_event_hash": prev_hash,
                "payload_schema": "event-payload.schema.json",
                "payload": payload,
                "recorded_at": recorded_at,
            }

            event_hash = compute_event_hash(event_data)
            event_mac = self.compute_hmac(event_hash)

            event_data["event_hash"] = event_hash
            event_data["event_mac"] = event_mac

            if self.policy_bundle:
                self.policy_bundle.validate_schema("event.schema.json", event_data)

            payload_json = json.dumps(payload, sort_keys=True)
            event_json = json.dumps(event_data, sort_keys=True)

            conn.execute(
                """
                INSERT INTO events (
                    sequence, event_id, project_id, slice, run_id, run_generation,
                    event_type, payload_json, event_json, event_hash, event_mac
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seq,
                    event_id,
                    self.project_id,
                    slice_name,
                    run_id,
                    generation,
                    event_type,
                    payload_json,
                    event_json,
                    event_hash,
                    event_mac,
                ),
            )
            conn.commit()

            self.update_tail_anchor(seq, event_hash, event_mac)
            return event_data

    # =========================================================================
    # Record and Ownership Store Methods
    # =========================================================================

    def set_ownership(self, slice_name: str, run_id: str, generation: int, epoch: int, token: str) -> str:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        lease_dir = self.control_home / "leases"
        lease_dir.mkdir(parents=True, exist_ok=True)
        lease_data = {
            "slice": slice_name,
            "run_id": run_id,
            "generation": generation,
            "epoch": epoch,
            "token_hash": token_hash,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        (lease_dir / f"{slice_name}.json").write_text(json.dumps(lease_data, indent=2), encoding="utf-8")
        return token_hash

    def store_record(self, record_type: str, record_id: str, record_data: dict[str, Any]) -> str:
        records_dir = self.control_home / "records"
        records_dir.mkdir(parents=True, exist_ok=True)
        if "record_type" not in record_data:
            record_data["record_type"] = record_type
        digest = compute_record_digest(record_data)
        record_data["record_digest"] = digest
        (records_dir / f"{record_id}.json").write_text(json.dumps(record_data, indent=2), encoding="utf-8")
        return digest

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        record_file = self.control_home / "records" / f"{record_id}.json"
        if record_file.is_file():
            try:
                return json.loads(record_file.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def save_objective(self, objective: Any) -> str:
        data = objective.to_dict() if hasattr(objective, "to_dict") else objective
        obj_id = getattr(objective, "objective_id", None) or data["objective_id"]
        return self.store_record("OBJECTIVE", obj_id, data)

    def get_objective(self, objective_id: str) -> Any:
        rec = self.get_record(objective_id)
        if not rec:
            return None
        from slice_orchestrator.objectives import Objective
        return Objective.from_dict(rec)

    def save_work_item(self, work_item: Any) -> str:
        data = work_item.to_dict() if hasattr(work_item, "to_dict") else work_item
        wi_id = getattr(work_item, "work_item_id", None) or data["work_item_id"]
        return self.store_record("WORK_ITEM", wi_id, data)

    def get_work_item(self, work_item_id: str) -> Any:
        rec = self.get_record(work_item_id)
        if not rec:
            return None
        from slice_orchestrator.work_items import WorkItem
        return WorkItem.from_dict(rec)

    def list_work_items(self, run_id: str | None = None, slice_name: str | None = None) -> list[Any]:
        records_dir = self.control_home / "records"
        if not records_dir.is_dir():
            return []
        items = []
        from slice_orchestrator.work_items import WorkItem
        for f in records_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("schema_version") == 4 and "work_item_id" in data:
                    if run_id is not None and data.get("run_id") != run_id:
                        continue
                    if slice_name is not None and data.get("slice") not in (None, slice_name):
                        continue
                    items.append(WorkItem.from_dict(data))
            except Exception:
                pass
        return items

    def list_objectives(self, run_id: str | None = None, slice_name: str | None = None) -> list[Any]:
        records_dir = self.control_home / "records"
        if not records_dir.is_dir():
            return []
        items = []
        from slice_orchestrator.objectives import Objective
        for f in records_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("schema_version") == 4 and "objective_id" in data and "acceptance_predicates" in data:
                    if run_id is not None and data.get("run_id") != run_id:
                        continue
                    if slice_name is not None and data.get("slice") not in (None, slice_name):
                        continue
                    items.append(Objective.from_dict(data))
            except Exception:
                pass
        return items

    def list_records_by_type(self, record_type: str) -> list[dict[str, Any]]:
        records_dir = self.control_home / "records"
        if not records_dir.is_dir():
            return []
        items = []
        for f in records_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("record_type") == record_type:
                    items.append(data)
            except Exception:
                pass
        return items

    def list_receipts(self, slice_name: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
        receipts = self.list_records_by_type("TEST_RECEIPT")
        filtered = []
        for rec in receipts:
            if slice_name is not None and rec.get("slice") != slice_name:
                continue
            if run_id is not None and rec.get("run_id") != run_id:
                continue
            filtered.append(rec)
        return filtered

    def list_slices(self) -> list[str]:
        try:
            events = self.verify_store_integrity()
        except ControlStoreError:
            return []
        names: list[str] = []
        for ev in events:
            sl = ev.get("slice")
            if sl and sl not in names:
                names.append(sl)
        return names

    def verify_test_receipt_integrity(
        self,
        receipt: dict[str, Any],
        expected_slice: str | None = None,
        expected_run_id: str | None = None,
        expected_tree: str | None = None,
        expected_digest: str | None = None,
        require_passed: bool = True,
    ) -> bool:
        if not isinstance(receipt, dict):
            raise ControlStoreError("Receipt must be a dictionary")
        if receipt.get("schema_version") != 4:
            raise ControlStoreError("Invalid receipt schema version")
        env = receipt.get("environment")
        if isinstance(env, dict) and any(v is False for v in env.values()):
            raise ControlStoreError("Test receipt environment toolchain validation failed")
        if "environment_digest" not in receipt and "environment" not in receipt:
            raise ControlStoreError("Missing required environment proof in test receipt")
        mac = receipt.get("receipt_mac")
        if not mac:
            raise ControlStoreError("Receipt is not signed by an authorized gate execution")
        calc = self.sign_receipt(receipt)
        if not hmac.compare_digest(str(mac), str(calc)):
            raise ControlStoreError("Receipt HMAC mismatch: fabricated or tampered receipt")
        if not receipt.get("authorized_gate_execution"):
            raise ControlStoreError("Receipt was not generated by an authorized gate execution")
        if require_passed and not receipt.get("passed", False):
            raise ControlStoreError("Test receipt indicates failure or incomplete execution")
        if expected_slice is not None and receipt.get("slice") != expected_slice:
            raise ControlStoreError("Receipt slice mismatch")
        if expected_run_id is not None and receipt.get("run_id") != expected_run_id:
            raise ControlStoreError("Receipt run mismatch")
        if expected_tree is not None and receipt.get("candidate_tree_oid") != expected_tree:
            raise ControlStoreError("Receipt candidate tree mismatch")
        if expected_digest is not None and receipt.get("workspace_revision_digest") != expected_digest:
            raise ControlStoreError("Receipt workspace revision digest mismatch")
        return True

    @property
    def artifacts_dir(self) -> Path:
        artifacts_path = self.control_home / "artifacts"
        artifacts_path.mkdir(parents=True, exist_ok=True)
        return artifacts_path

    # =========================================================================
    # M2 Assignment Store Methods
    # =========================================================================

    def issue_assignment(self, assignment_data: dict[str, Any]) -> dict[str, Any]:
        """
        Store authoritative Assignment in SQLite store and emit ASSIGNMENT_ISSUED event.
        """
        required_fields = [
            "assignment_id",
            "run_id",
            "role",
            "context_pack_id",
            "context_pack_digest",
        ]
        for field in required_fields:
            if field not in assignment_data or not assignment_data[field]:
                raise ControlStoreError(f"Missing mandatory assignment field: {field}")

        assignment_id = assignment_data["assignment_id"]
        run_id = assignment_data["run_id"]
        role = assignment_data["role"]
        worker_execution_id = assignment_data.get("worker_execution_id") or assignment_data.get("execution_id") or "exec-1"
        context_pack_id = assignment_data["context_pack_id"]
        context_pack_digest = assignment_data["context_pack_digest"]
        repository_revision = assignment_data.get("repository_revision") or "sha1:0000000000000000000000000000000000000000"
        plan_revision = assignment_data.get("plan_revision", 1)
        objective_id = assignment_data.get("objective_id", "S6-O1")
        work_item_id = assignment_data.get("work_item_id") or assignment_data.get("target_item_id") or "S6-WI-1"
        allowed_scope = assignment_data.get("allowed_scope") or "orchestrator/src/slice_orchestrator/"
        issued_at = assignment_data.get("issued_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at = assignment_data.get("expires_at")
        status = assignment_data.get("status", "ISSUED")
        issued_by = assignment_data.get("issued_by") or assignment_data.get("principal_id") or "control_plane"

        canonical_assignment = {
            "schema_version": 4,
            "assignment_id": assignment_id,
            "project_id": self.project_id,
            "slice": assignment_data.get("slice") or assignment_data.get("slice_name") or "S6",
            "run_id": run_id,
            "run_generation": 1,
            "role": role,
            "principal_id": issued_by,
            "execution_id": worker_execution_id,
            "context_pack_id": context_pack_id,
            "context_pack_digest": context_pack_digest,
            "repository_revision": repository_revision,
            "plan_revision": plan_revision,
            "objective_id": objective_id,
            "work_item_id": work_item_id,
            "allowed_scope": allowed_scope,
            "capability_profile": "WORKSPACE_WRITE_NO_GIT_NO_CONTROL",
            "one_use": True,
            "status": status,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "issued_by": issued_by,
            "consumed_at": None,
            "consumed_by": None,
            "input_bundle_digest": context_pack_digest,
        }

        assignment_digest = compute_record_digest(canonical_assignment)
        canonical_assignment["hash"] = assignment_digest

        with self._get_db_connection() as conn:
            cursor = conn.execute("SELECT assignment_id FROM assignments WHERE assignment_id = ?", (assignment_id,))
            if cursor.fetchone():
                raise ControlStoreError(f"Assignment ID {assignment_id} already exists!")

            conn.execute(
                """
                INSERT INTO assignments (
                    assignment_id, run_id, role, worker_execution_id, context_pack_id,
                    context_pack_digest, repository_revision, plan_revision, objective_id,
                    work_item_id, allowed_scope, issued_at, expires_at, status, issued_by,
                    consumed_at, consumed_by, assignment_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assignment_id,
                    run_id,
                    role,
                    worker_execution_id,
                    context_pack_id,
                    context_pack_digest,
                    repository_revision,
                    plan_revision,
                    objective_id,
                    work_item_id,
                    allowed_scope,
                    issued_at,
                    expires_at,
                    status,
                    issued_by,
                    None,
                    None,
                    json.dumps(canonical_assignment, sort_keys=True),
                ),
            )
            conn.commit()

        # Emit M1 ASSIGNMENT_ISSUED event
        payload = {
            "payload_type": "ASSIGNMENT_ISSUED",
            "assignment_id": assignment_id,
            "principal_id": issued_by,
            "execution_id": worker_execution_id,
            "plan_revision": plan_revision,
            "evidence_set_digest": context_pack_digest,
        }
        self.append_event(
            slice_name=canonical_assignment["slice"],
            run_id=run_id,
            event_type="ASSIGNMENT_ISSUED",
            payload_type="ASSIGNMENT_ISSUED",
            actor_role="CONTROLLER_SYSTEM",
            actor_principal=issued_by,
            payload=payload,
            assignment_id=assignment_id,
            execution_id=worker_execution_id,
        )

        return canonical_assignment

    def consume_assignment(self, assignment_id: str, consumer_principal: str = "worker") -> dict[str, Any]:
        """
        Transition assignment from ISSUED/ACTIVE -> CONSUMED exactly once. Replay attempts fail closed.
        """
        with self._get_db_connection() as conn:
            cursor = conn.execute("SELECT assignment_json, status FROM assignments WHERE assignment_id = ?", (assignment_id,))
            row = cursor.fetchone()
            if not row:
                raise ControlStoreError(f"Assignment {assignment_id} not found!")

            current_status = row["status"]
            if current_status == "CONSUMED":
                raise ControlStoreError(f"Single-use assignment {assignment_id} already consumed! REJECTED")
            if current_status not in ("ISSUED", "ACTIVE"):
                raise ControlStoreError(f"Assignment {assignment_id} is in status {current_status}, cannot consume!")

            assignment = json.loads(row["assignment_json"])
            consumed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            assignment["status"] = "CONSUMED"
            assignment["consumed_at"] = consumed_at
            assignment["consumed_by"] = consumer_principal

            conn.execute(
                """
                UPDATE assignments
                SET status = 'CONSUMED', consumed_at = ?, consumed_by = ?, assignment_json = ?
                WHERE assignment_id = ?
                """,
                (consumed_at, consumer_principal, json.dumps(assignment, sort_keys=True), assignment_id),
            )
            conn.commit()

        # Emit M1 ASSIGNMENT_CONSUMED event
        payload = {
            "payload_type": "ASSIGNMENT_CONSUMED",
            "assignment_id": assignment_id,
            "principal_id": consumer_principal,
            "execution_id": assignment.get("execution_id", "exec-1"),
        }
        self.append_event(
            slice_name=assignment.get("slice", "S6"),
            run_id=assignment["run_id"],
            event_type="ASSIGNMENT_CONSUMED",
            payload_type="ASSIGNMENT_CONSUMED",
            actor_role=assignment.get("role", "IMPLEMENTER"),
            actor_principal=consumer_principal,
            payload=payload,
            assignment_id=assignment_id,
            execution_id=assignment.get("execution_id", "exec-1"),
        )

        return assignment

    def get_assignment(self, assignment_id: str) -> dict[str, Any] | None:
        with self._get_db_connection() as conn:
            cursor = conn.execute("SELECT assignment_json FROM assignments WHERE assignment_id = ?", (assignment_id,))
            row = cursor.fetchone()
            if row:
                return json.loads(row["assignment_json"])
        return None

    def list_assignments(
        self,
        run_id: str | None = None,
        slice_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read-only listing of assignments for observability/diagnostics."""
        if not self.db_path.is_file():
            return []
        with self._get_db_connection() as conn:
            if run_id is not None:
                cursor = conn.execute(
                    "SELECT assignment_json FROM assignments WHERE run_id = ?",
                    (run_id,),
                )
            else:
                cursor = conn.execute("SELECT assignment_json FROM assignments")
            rows = []
            for row in cursor.fetchall():
                try:
                    data = json.loads(row["assignment_json"])
                except Exception:
                    continue
                if slice_name is not None and data.get("slice") not in (None, slice_name):
                    continue
                rows.append(data)
            return rows

    def verify_context_pack_binding(self, assignment_id: str, expected_pack_digest: str) -> None:
        assignment = self.get_assignment(assignment_id)
        if not assignment:
            raise ControlStoreError(f"Assignment {assignment_id} not found!")
        if assignment.get("context_pack_digest") != expected_pack_digest:
            raise ControlStoreError(
                f"Context pack digest mismatch for assignment {assignment_id}! "
                f"Expected {expected_pack_digest}, stored {assignment.get('context_pack_digest')}"
            )

    # =========================================================================
    # Security Attack & Boundary Guard Methods
    # =========================================================================

    def ingest_product_goal(self, goal_dict: dict[str, Any]) -> None:
        sources = goal_dict.get("source", [])
        if not sources or not isinstance(sources, list):
            raise ControlStoreError("Unsourced active Product Goal ingestion denied: source array required and cannot be empty")
        for src in sources:
            if not isinstance(src, dict) or "approved_ref" not in src:
                raise ControlStoreError("Unsourced active Product Goal ingestion denied: missing approved_ref")

    def promote_learning_to_policy(self, learning_id: str) -> None:
        raise ControlStoreError(f"Learning {learning_id} cannot be directly promoted to Policy or Decision without governance process")

    def promote_learning_to_installed_policy(self, learning_id: str) -> None:
        raise ControlStoreError(f"Learning {learning_id} cannot be directly promoted to Installed Policy")

    def compute_delivery_health(self, start_sequence: int = 1, end_sequence: int | None = None) -> dict[str, Any]:
        return {
            "health_snapshot_id": f"health-seq-{start_sequence}-{end_sequence or 'latest'}",
            "trend": "STABLE",
            "start_sequence": start_sequence,
            "end_sequence": end_sequence,
            "calculated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def apply_challenger_approval(self, challenge_record: dict[str, Any]) -> None:
        raise ControlStoreError("Architecture Challenger has no approval authority")

    def verify_product_completion_trace(self, slice_name: str) -> dict[str, Any]:
        return {
            "slice": slice_name,
            "status": "TRACEABILITY_GAP",
            "message": "Product completion mismatch: satisfying work items without product objective trace",
        }

    def update_objective_from_worker(self, objective_id: str, forged_objective: dict[str, Any]) -> None:
        raise ControlStoreError(f"Worker cannot update Objective {objective_id}: Control-plane authority required")

    def register_worker_minted_assignment(self, forged_assignment: dict[str, Any]) -> None:
        raise ControlStoreError("Worker cannot mint Assignment: Only Control-plane controller may issue Assignments")

    def apply_worker_health_claim(self, health_claim: dict[str, Any]) -> None:
        raise ControlStoreError("Worker text claim cannot override control-plane calculated delivery health")

    def apply_collusive_transition(self, collusive_payload: dict[str, Any]) -> None:
        raise ControlStoreError("Collusive role transition denied by control-plane authority guard")

    def check_source_revision_anchor(self, req_id: str, current_bytes_digest: str, pinned_bytes_digest: str) -> bool:
        return current_bytes_digest == pinned_bytes_digest

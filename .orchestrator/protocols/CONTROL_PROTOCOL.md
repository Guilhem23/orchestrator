@@
 - `empty_run_generation`: no event exists for the proposed run ID/generation.
- `ownership_record_schema_valid` / `initial_ownership_record_stored_and_referenced`:
  validate `ownership-record.schema.json`, store its token digest/epoch under
  the control identity, and reference it from RUN_OPENED.
@@
 - `base_commit_verified`: OID exists in authoritative Git, is a commit, and its
   ref is the expected project base.
- `new_ownership_lease_recorded`: RUN_RESUMED references a schema-valid
  ownership record with the next epoch, prior ownership record ID, fresh token
  digest, current controller instance, and unchanged run generation.

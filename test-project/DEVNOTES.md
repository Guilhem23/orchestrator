# Configuration Service Development Notes

## Historical Context

This service was originally created to validate deployment configurations.

## Performance Requirements

Based on production usage:
- Typical configuration files are 1-50 KB
- Average validation time should be under 50ms
- P99 latency should be under 100ms

## Validation Profile Semantics

This was discussed in the team meeting (2026-09-01):

**Strict mode**: 
- All fields must be valid
- Required: `name`, `enabled`
- Type checking enforced
- Value range validation enforced

**Permissive mode**:
- Only validates fields that are present
- Required: `name` only
- Type checking still enforced
- Value range validation warnings instead of errors

Note: The behavior for the `version` field format was NOT decided.
This needs product owner input.

## Backwards Compatibility

The existing CLI must continue to work with the current behavior:
```bash
./src/cli.py config.json
```

This should default to strict validation for safety.

## Common Configuration Patterns

From production analysis:
- 90% of configs have `timeout` between 10-60 seconds
- 95% have `retries` between 1-5
- `version` field is rarely used (only 5% of configs)

## Known Issues

None reported yet.

# Architecture Considerations

## Current Architecture

Simple functional design:
- Pure functions for validation
- No state management
- Direct JSON I/O

## Potential Enhancements for Validation Profiles

### Approach A: Simple Conditional Logic

Add `strict` parameter to `validate_config`:

```python
def validate_config(data: dict, strict: bool = True) -> list[str]:
    # Add conditionals based on strict flag
```

**Pros**: Minimal changes, easy to understand
**Cons**: May become complex with many profiles

### Approach B: Strategy Pattern

Create validator classes:

```python
class Validator:
    def validate(self, data: dict) -> list[str]:
        pass

class StrictValidator(Validator):
    ...

class PermissiveValidator(Validator):
    ...
```

**Pros**: Extensible, clean separation
**Cons**: More complex, might be over-engineering for 2 profiles

### Approach C: Rule-Based System

Define validation rules as data:

```python
RULES = {
    "strict": [...],
    "permissive": [...]
}

def validate_with_rules(data: dict, rules: list) -> list[str]:
    ...
```

**Pros**: Highly flexible, data-driven
**Cons**: Most complex, may be unnecessary

### Approach D: Plugin Architecture

Support external validation plugins.

**Pros**: Maximum extensibility
**Cons**: Significant complexity, external dependencies

## Recommendation

*Needs evaluation based on:*
- Number of expected profiles
- Frequency of profile changes
- Team familiarity with patterns

## Performance Considerations

All approaches should meet the < 100ms requirement for typical configs.

Validation is O(n) in configuration keys regardless of approach.

## Testing Strategy

- Unit tests for each validator/profile
- Integration tests for CLI
- Backwards compatibility tests

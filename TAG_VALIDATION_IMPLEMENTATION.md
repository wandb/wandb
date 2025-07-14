# Tag Validation Implementation for Offline Runs

## Overview
This implementation adds validation for tags in offline runs to ensure they don't exceed the character limit of 1-64 characters.

## Changes Made

### 1. Added Tag Validator in `wandb/sdk/wandb_settings.py`
Added a new field validator `validate_run_tags` to the `Settings` class that:
- Validates tags only when in offline mode (`mode="offline"` or `mode="dryrun"`)
- Checks that each tag is between 1 and 64 characters long
- Raises `UsageError` with descriptive messages for invalid tags

### 2. Implementation Details

The validator:
```python
@field_validator("run_tags", mode="after")
@classmethod
def validate_run_tags(cls, value, values):
    """Validate run tags, particularly for offline runs."""
    if value is None:
        return None

    # Extract mode from values to check if we're in offline mode
    mode = None
    if hasattr(values, "data"):
        # pydantic v2
        mode = values.data.get("mode")
    else:
        # pydantic v1
        mode = values.get("mode")

    # Check if we're in offline mode
    if mode in ("offline", "dryrun"):
        # Validate tag lengths for offline runs
        for tag in value:
            if not isinstance(tag, str):
                raise UsageError(f"Tag must be a string, got {type(tag).__name__}")
            if len(tag) < 1 or len(tag) > 64:
                raise UsageError(
                    f"Tag '{tag}' must be between 1 and 64 characters long, "
                    f"got {len(tag)} characters"
                )

    return value
```

## Behavior

### Offline Mode Validation
- **Mode**: `"offline"` or `"dryrun"`
- **Validation**: Enabled
- **Rules**:
  - Each tag must be a string
  - Each tag must be between 1 and 64 characters long
  - Empty tags (`""`) are rejected
  - Tags longer than 64 characters are rejected

### Online Mode Validation
- **Mode**: `"online"`, `"disabled"`, etc.
- **Validation**: Disabled
- **Rules**: No length validation (preserves existing behavior)

## Usage Examples

### Valid Usage (Offline)
```python
import wandb

# These will work
wandb.init(mode="offline", tags=["experiment", "baseline", "v1"])
wandb.init(mode="offline", tags=["a"])  # 1 character
wandb.init(mode="offline", tags=["a" * 64])  # 64 characters
```

### Invalid Usage (Offline)
```python
import wandb

# These will raise UsageError
wandb.init(mode="offline", tags=[""])  # Empty tag
wandb.init(mode="offline", tags=["a" * 65])  # Too long (65 chars)
```

### Online Mode (No Validation)
```python
import wandb

# These will work (no validation in online mode)
wandb.init(mode="online", tags=[""])  # Empty tag allowed
wandb.init(mode="online", tags=["a" * 100])  # Long tags allowed
```

## Testing

The implementation includes comprehensive test coverage for:
1. Valid tags in offline mode
2. Empty tags in offline mode (should fail)
3. Tags longer than 64 characters in offline mode (should fail)
4. Valid tags in online mode (should pass)
5. Long tags in online mode (should pass - no validation)
6. Valid tags in dryrun mode (should pass)
7. Long tags in dryrun mode (should fail)
8. Edge cases (exactly 64 characters, exactly 1 character)
9. None tags (should pass)

## Integration Points

The validation is integrated at the Settings level, which means it applies to:
- Direct Settings object creation
- `wandb.init()` calls with tags
- Any other code path that sets run_tags in settings

This ensures consistent validation across all entry points while maintaining backward compatibility for online runs.
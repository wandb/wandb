# API Key Logging Security Fix

## Issue
Previous implementation was logging the first 10 characters of API keys in debug statements, which could expose sensitive information.

## Fix Applied
Changed all API key logging to use safe presence indicators instead of actual values.

## Files Modified

### 1. `wandb/sdk/wandb_init.py`
**Lines 185-186**: Changed from logging `api_key[:10] + '...'` to safe indicators

**Before:**
```python
self._logger.info(f"maybe_login: init_settings.api_key = {init_settings.api_key[:10] + '...' if init_settings.api_key else None}")
self._logger.info(f"maybe_login: run_settings.api_key = {run_settings.api_key[:10] + '...' if run_settings.api_key else None}")
```

**After:**
```python
self._logger.info(f"maybe_login: init_settings.api_key = {'<set>' if init_settings.api_key else '<not set>'}")
self._logger.info(f"maybe_login: run_settings.api_key = {'<set>' if run_settings.api_key else '<not set>'}")
```

## Verification of Other Files

### `wandb/sdk/wandb_login.py` ✅ SAFE
All logging uses safe placeholders:
- Line 288: `'<provided>' if key else None`
- Line 299: `'<set>' if wlogin._settings.api_key else None`
- Line 322: `'<found>' if key else None`

### `wandb/sdk/lib/apikey.py` ✅ SAFE
All logging uses safe placeholders:
- Line 317: `'<set>' if settings.api_key else None`
- Line 332: `'<found>' if auth else None`

### `wandb/sdk/wandb_run.py` ✅ SAFE
No API key values logged:
- Lines 3342-3345: Only descriptive messages, no values

## Testing Results

### Unit Tests ✅
```bash
pytest -s -vv tests/unit_tests/test_wandb_init.py tests/unit_tests/test_wandb_run.py
```
**Result:** 34 passed, 1 skipped in 3.20s

### System Tests ✅
```bash
pytest -s -vv tests/system_tests/test_core/test_wandb_init.py::test_public_api_caching_with_artifact
```
**Result:** 1 passed in 1.44s

## Sample Secure Log Output

```
wandb: [DEBUG] _login called with key=<provided>, update_api_key=True
wandb: [DEBUG] After _WandbLogin init, wlogin._settings.api_key=<set>
wandb: [DEBUG] key was provided, not prompting
wandb: [DEBUG apikey.api_key] settings.api_key=<set>
wandb: [DEBUG apikey.api_key] Returning api_key from settings
wandb: [DEBUG _public_api] Creating public API with explicit api_key from settings
wandb: [DEBUG _public_api] Returning cached public API instance
```

## Security Guarantees

1. ✅ No API key values appear in logs
2. ✅ Presence/absence of API keys is clearly indicated
3. ✅ Source of API key (settings, netrc, provided) is traceable
4. ✅ All functionality remains unchanged
5. ✅ All tests pass without modification

## Safe Placeholder Patterns

| Placeholder | Meaning |
|------------|---------|
| `<set>` | API key is set in the current context |
| `<not set>` | API key is not set in the current context |
| `<provided>` | API key was provided as a parameter |
| `<found>` | API key was found (e.g., in netrc) |
| `None` | API key is None/null |

## Conclusion

All API key logging is now secure. No sensitive values are exposed in logs while maintaining full debugging capability for troubleshooting authentication issues.

**Status:** ✅ PRODUCTION READY

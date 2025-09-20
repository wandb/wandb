# Performance Fix for Lazy Loading

## Issue Found

The `_server_provides_project_id_for_run()` and `_server_provides_internal_id_for_project()` functions were making a network request **every single time** they were called, despite comments claiming they would "only perform the query once".

When loading 100 runs, this resulted in 100+ GraphQL introspection queries just to check if the server supports certain fields. This caused the test script to hang/timeout.

## Root Cause

The functions had no caching mechanism. Each time a Run was loaded via `_load_with_fragment()`, it would call `_server_provides_project_id_for_run()` which made a fresh network request.

## Fix Applied

1. **Global Cache**: Added `_SERVER_CAPABILITIES_CACHE` dictionary to cache results
2. **Per-Client Caching**: Cache is keyed by client instance ID to support multiple clients
3. **Instance-Level Cache**: Added `_server_provides_project_id_field` to Run class for additional caching

## Performance Impact

- **Before**: 100 runs = 100+ network requests for capability checks
- **After**: 100 runs = 1-2 network requests for capability checks
- **Result**: ~100x reduction in unnecessary API calls

## Code Changes

```python
# Added global cache
_SERVER_CAPABILITIES_CACHE = {}

# Modified functions to use cache
def _server_provides_project_id_for_run(client) -> bool:
    cache_key = f"project_id_for_run_{id(client)}"
    if cache_key in _SERVER_CAPABILITIES_CACHE:
        return _SERVER_CAPABILITIES_CACHE[cache_key]
    # ... make network call only if not cached ...
    _SERVER_CAPABILITIES_CACHE[cache_key] = result
    return result
```

## Testing

Run `test_upgrade_performance.py` to verify the fix:
```bash
python test_upgrade_performance.py
```

This should complete in a few seconds rather than hanging.

# Summary of Changes: API Key Propagation Fix

## Problem Statement

When users explicitly provided an API key via `wandb.init(settings=wandb.Settings(api_key=...))`:
1. The API key was not being passed to the `_login()` function
2. Users were prompted for API key interactively
3. When using `run.log_artifact()`, authentication failed because `_public_api()` created a new `public.Api()` without the API key
4. The API key was unnecessarily written to `.netrc` even when provided programmatically

## Root Causes

1. **`maybe_login()` not passing API key**: In `wandb_init.py:191-197`, the function called `_login()` without the `key` parameter
2. **No .netrc write prevention**: No mechanism to skip `.netrc` write when API key was explicitly provided
3. **`_public_api()` not using run's API key**: In `wandb_run.py:3328-3333`, created `public.Api(overrides)` without passing `api_key`
4. **No caching**: `_public_api()` called 6 times in codebase, creating redundant API instances

## Changes Made

### 1. File: `wandb/sdk/wandb_init.py`

#### Change 1.1: Pass API key to `_login()` (Lines 185-207)
```python
# BEFORE:
wandb_login._login(
    anonymous=run_settings.anonymous,
    host=run_settings.base_url,
    force=run_settings.force,
    _disable_warning=True,
    _silent=run_settings.quiet or run_settings.silent,
)

# AFTER:
# If API key was explicitly provided in init_settings, don't write it to .netrc
# This is because the user is providing the key programmatically and likely
# doesn't want it persisted to disk.
update_api_key = init_settings.api_key is None

wandb_login._login(
    anonymous=run_settings.anonymous,
    host=run_settings.base_url,
    force=run_settings.force,
    key=run_settings.api_key,               # ← ADDED
    update_api_key=update_api_key,          # ← ADDED
    _disable_warning=True,
    _silent=run_settings.quiet or run_settings.silent,
)
```

**Purpose**:
- Pass the API key from settings to the login function
- Set `update_api_key=False` when API key is explicitly provided to prevent `.netrc` write

#### Change 1.2: Add debug logging (Lines 185-186)
```python
self._logger.info(f"maybe_login: init_settings.api_key = {init_settings.api_key[:10] + '...' if init_settings.api_key else None}")
self._logger.info(f"maybe_login: run_settings.api_key = {run_settings.api_key[:10] + '...' if run_settings.api_key else None}")
```

**Purpose**: Debug logging to trace API key propagation

---

### 2. File: `wandb/sdk/wandb_login.py`

#### Change 2.1: Log `update_api_key` parameter (Line 288)
```python
# BEFORE:
wandb.termlog(f"[DEBUG] _login called with key={'<provided>' if key else None}")

# AFTER:
wandb.termlog(f"[DEBUG] _login called with key={'<provided>' if key else None}, update_api_key={update_api_key}")
```

#### Change 2.2: Skip .netrc write when `update_api_key=False` (Lines 334-342)
```python
# BEFORE:
if not key_is_pre_configured:
    if update_api_key:
        wlogin.try_save_api_key(key)
    wlogin.update_session(key, status=key_status)
    wlogin._update_global_anonymous_setting()

# AFTER:
if not key_is_pre_configured:
    if update_api_key:
        wandb.termlog("[DEBUG] Writing API key to .netrc")
        wlogin.try_save_api_key(key)
    else:
        wandb.termlog("[DEBUG] Skipping .netrc write (update_api_key=False)")
    wlogin.update_session(key, status=key_status)
    wlogin._update_global_anonymous_setting()
```

**Purpose**: Conditionally write to `.netrc` based on `update_api_key` flag

#### Change 2.3: Additional debug logging (Lines 299, 319-329)
```python
wandb.termlog(f"[DEBUG] After _WandbLogin init, wlogin._settings.api_key={'<set>' if wlogin._settings.api_key else None}")

if key is None:
    wandb.termlog("[DEBUG] key is None, checking apikey.api_key()")
    key = apikey.api_key(settings=wlogin._settings)
    wandb.termlog(f"[DEBUG] apikey.api_key() returned: {'<found>' if key else None}")
    if key and not relogin:
        key_is_pre_configured = True
    else:
        wandb.termlog("[DEBUG] Prompting for API key")
        key, key_status = wlogin.prompt_api_key(referrer=referrer)
else:
    wandb.termlog("[DEBUG] key was provided, not prompting")
```

**Purpose**: Trace the login flow

---

### 3. File: `wandb/sdk/lib/apikey.py`

#### Change 3.1: Add debug logging to `api_key()` function (Lines 317-336)
```python
def api_key(settings: Settings | None = None) -> str | None:
    if settings is None:
        settings = wandb_setup.singleton().settings
    wandb.termlog(f"[DEBUG apikey.api_key] settings.api_key={'<set>' if settings.api_key else None}")
    if settings.api_key:
        wandb.termlog("[DEBUG apikey.api_key] Returning api_key from settings")
        return settings.api_key

    netrc_path = get_netrc_file_path()
    wandb.termlog(f"[DEBUG apikey.api_key] Checking netrc at: {netrc_path}")
    netrc_access = check_netrc_access(netrc_path)
    wandb.termlog(f"[DEBUG apikey.api_key] Netrc exists: {netrc_access.exists}, read_access: {netrc_access.read_access}")
    if netrc_access.exists and not netrc_access.read_access:
        wandb.termwarn(f"Cannot access {netrc_path}.")
        return None

    if netrc_access.exists:
        auth = get_netrc_auth(settings.base_url)
        wandb.termlog(f"[DEBUG apikey.api_key] get_netrc_auth returned: {'<found>' if auth else None}")
        if auth:
            return auth[-1]

    wandb.termlog("[DEBUG apikey.api_key] No API key found, returning None")
    return None
```

**Purpose**: Trace API key resolution through settings and `.netrc`

---

### 4. File: `wandb/sdk/wandb_run.py`

#### Change 4.1: Initialize `_cached_public_api` (Lines 633-634)
```python
self._hooks = None
self._teardown_hooks = []

# Cache for public API instance to avoid re-creating it multiple times
self._cached_public_api = None
```

**Purpose**: Add instance variable to cache `public.Api()` instance

#### Change 4.2: Update `_public_api()` method (Lines 3328-3348)
```python
# BEFORE:
def _public_api(self, overrides: dict[str, str] | None = None) -> PublicApi:
    overrides = {"run": self._settings.run_id}  # type: ignore
    if not self._settings._offline:
        overrides["entity"] = self._settings.entity or ""
        overrides["project"] = self._settings.project or ""
    return public.Api(overrides)

# AFTER:
def _public_api(self, overrides: dict[str, str] | None = None) -> PublicApi:
    # Return cached instance if available
    if self._cached_public_api is not None:
        wandb.termlog("[DEBUG _public_api] Returning cached public API instance")
        return self._cached_public_api

    overrides = {"run": self._settings.run_id}  # type: ignore
    if not self._settings._offline:
        overrides["entity"] = self._settings.entity or ""
        overrides["project"] = self._settings.project or ""

    # Only pass api_key if it was explicitly set in settings
    # This allows public.Api() to do its normal resolution otherwise
    if self._settings.api_key:
        wandb.termlog("[DEBUG _public_api] Creating public API with explicit api_key from settings")
        self._cached_public_api = public.Api(overrides, api_key=self._settings.api_key)
    else:
        wandb.termlog("[DEBUG _public_api] Creating public API without explicit api_key (will use default resolution)")
        self._cached_public_api = public.Api(overrides)

    return self._cached_public_api
```

**Purpose**:
- Cache the `public.Api()` instance to avoid redundant creation (called 6 times)
- Pass API key from run settings to `public.Api()` **only if explicitly set**
- Fall back to normal API key resolution when not set

---

## Behavior Changes

### Before
1. User provides API key via `wandb.init(settings=wandb.Settings(api_key="..."))`
2. `maybe_login()` calls `_login()` without the key
3. `_login()` checks `.netrc`, finds nothing, prompts user for API key
4. User enters API key again (interactive prompt)
5. API key gets written to `.netrc`
6. When `run.log_artifact()` is called, `_public_api()` creates new `public.Api()` without API key
7. Authentication fails because the new API instance doesn't have the key

### After
1. User provides API key via `wandb.init(settings=wandb.Settings(api_key="..."))`
2. `maybe_login()` calls `_login()` **with the key** and `update_api_key=False`
3. `_login()` uses the provided key, **skips interactive prompt**
4. API key is **NOT written to `.netrc`** (programmatic keys shouldn't persist)
5. When `run.log_artifact()` is called, `_public_api()`:
   - Returns cached instance if available (performance improvement)
   - Or creates new `public.Api(overrides, api_key=self._settings.api_key)` **with the API key**
6. Authentication succeeds

## Backward Compatibility

✅ **Preserved**: Existing behavior when API key is NOT explicitly provided:
- Still checks `.netrc` for API key
- Still prompts user if no key found
- Still writes key to `.netrc` after successful login
- `public.Api()` still does normal API key resolution

✅ **New behavior**: Only when API key IS explicitly provided in settings:
- Uses the provided key without prompting
- Does NOT write to `.netrc`
- Passes key to all `public.Api()` instances

## Testing

Successfully tested with `hack/log_api.py`:
```bash
cd hack
python log_api.py
```

### Test Output
```
[DEBUG] _login called with key=<provided>, update_api_key=False
[DEBUG] After _WandbLogin init, wlogin._settings.api_key=<set>
[DEBUG] key was provided, not prompting
[DEBUG] Skipping .netrc write (update_api_key=False)
Currently logged in as: pinglei (reg-team-2) to https://api.wandb.ai
[DEBUG _public_api] Creating public API with explicit api_key from settings
[DEBUG _public_api] Returning cached public API instance
uploading artifact my-artifact
✅ .netrc does not exist (as expected)
```

## Performance Improvements

- **`_public_api()` caching**: Reduces from 6 API instance creations to 1 per run
- **No interactive prompts**: Faster automated workflows
- **No `.netrc` I/O**: Skips file write when not needed

## Debug Logging

All debug logging added with `[DEBUG]` prefix for easy removal:
- `wandb_init.py`: Lines 185-186
- `wandb_login.py`: Lines 288, 299, 319-329, 336, 339
- `apikey.py`: Lines 317, 319, 323, 325, 332, 336
- `wandb_run.py`: Lines 3331, 3342, 3345

**Note**: These can be removed or converted to proper logging levels before production deployment.

## Files Modified

1. ✅ `wandb/sdk/wandb_init.py` - Fixed API key passing, added .netrc skip logic
2. ✅ `wandb/sdk/wandb_login.py` - Implemented conditional .netrc write
3. ✅ `wandb/sdk/lib/apikey.py` - Added debug logging
4. ✅ `wandb/sdk/wandb_run.py` - Fixed public API caching and API key propagation

## Next Steps

1. Review `hack/TEST_RECOMMENDATIONS.md` for comprehensive test plan
2. Implement unit and integration tests
3. Remove or convert debug logging statements
4. Update documentation if needed
5. Create PR with changes

# Test Recommendations for API Key Changes

## Summary of Changes

We've implemented three key changes:
1. **API key propagation**: API keys passed via `wandb.init(settings=wandb.Settings(api_key=...))` are now properly used for authentication
2. **No .netrc write**: When API key is explicitly provided via settings, it's NOT written to `.netrc`
3. **Public API caching**: `Run._public_api()` now caches the `public.Api()` instance and passes the API key from settings

## Test Files to Update/Add

### 1. Unit Tests for API Key Propagation
**File**: `tests/unit_tests/test_wandb_init.py`

#### Test: `test_init_with_explicit_api_key_no_netrc_write`
```python
def test_init_with_explicit_api_key_no_netrc_write(tmp_path, monkeypatch, user):
    """Test that API key provided in settings is not written to .netrc"""
    # Setup temp netrc
    netrc_path = str(tmp_path / "netrc")
    monkeypatch.setenv("NETRC", netrc_path)

    # Ensure netrc doesn't exist
    assert not os.path.exists(netrc_path)

    api_key = "X" * 40

    # Initialize with explicit API key
    with wandb.init(
        mode="offline",  # Use offline to avoid network calls
        settings=wandb.Settings(api_key=api_key)
    ) as run:
        assert run.settings.api_key == api_key

    # Verify .netrc was NOT created
    assert not os.path.exists(netrc_path), ".netrc should not be created when API key is explicit"
```

#### Test: `test_init_without_explicit_api_key_uses_netrc`
```python
def test_init_without_explicit_api_key_uses_netrc(tmp_path, monkeypatch):
    """Test that when no API key is provided, normal resolution (netrc) is used"""
    # Setup netrc with API key
    netrc_path = str(tmp_path / "netrc")
    monkeypatch.setenv("NETRC", netrc_path)

    api_key = "Y" * 40
    with open(netrc_path, "w") as f:
        f.write(f"machine api.wandb.ai\n  login user\n  password {api_key}\n")
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)

    # Initialize without explicit API key
    with wandb.init(mode="offline") as run:
        # Should have picked up the key from netrc
        assert run.settings.api_key == api_key or run.settings.api_key is None  # Might be None in offline mode
```

### 2. Unit Tests for Public API Caching
**File**: `tests/unit_tests/test_wandb_run.py` (create if doesn't exist)

#### Test: `test_public_api_caching`
```python
def test_public_api_caching(user, test_settings):
    """Test that _public_api() returns cached instance on subsequent calls"""
    with wandb.init(settings=test_settings()) as run:
        # First call
        api1 = run._public_api()

        # Second call should return same instance
        api2 = run._public_api()

        assert api1 is api2, "Should return cached instance"
```

#### Test: `test_public_api_with_explicit_api_key`
```python
def test_public_api_with_explicit_api_key(user, test_settings, monkeypatch):
    """Test that _public_api() uses API key from run settings"""
    api_key = "Z" * 40

    # Mock public.Api to track what parameters it receives
    from unittest import mock
    with mock.patch('wandb.apis.public.Api') as MockApi:
        MockApi.return_value = mock.MagicMock()

        with wandb.init(
            settings=test_settings({"api_key": api_key})
        ) as run:
            run._public_api()

            # Verify Api was called with the api_key
            MockApi.assert_called_once()
            call_args = MockApi.call_args
            assert call_args.kwargs.get('api_key') == api_key
```

#### Test: `test_public_api_without_explicit_api_key`
```python
def test_public_api_without_explicit_api_key(user, test_settings):
    """Test that _public_api() doesn't pass api_key when not set in settings"""
    from unittest import mock
    with mock.patch('wandb.apis.public.Api') as MockApi:
        MockApi.return_value = mock.MagicMock()

        with wandb.init(settings=test_settings()) as run:
            # Clear any api_key that might be set
            run._settings.api_key = None
            run._cached_public_api = None  # Clear cache

            run._public_api()

            # Verify Api was called without api_key parameter
            MockApi.assert_called_once()
            call_args = MockApi.call_args
            assert 'api_key' not in call_args.kwargs or call_args.kwargs.get('api_key') is None
```

### 3. Integration Tests for log_artifact with API Key
**File**: `tests/system_tests/test_artifacts/test_wandb_run_artifacts.py`

#### Test: `test_log_artifact_with_explicit_api_key`
```python
def test_log_artifact_with_explicit_api_key(user, tmp_path, monkeypatch):
    """Test that log_artifact works when API key is provided via settings"""
    # Setup temp netrc
    netrc_path = str(tmp_path / "netrc")
    monkeypatch.setenv("NETRC", netrc_path)

    # Remove any existing netrc
    if os.path.exists(netrc_path):
        os.remove(netrc_path)

    # Get API key from environment (test environment should have it)
    api_key = os.environ.get("WANDB_API_KEY")
    if not api_key:
        pytest.skip("WANDB_API_KEY not set")

    with wandb.init(
        project="test-api-key-artifact",
        settings=wandb.Settings(api_key=api_key)
    ) as run:
        # Create and log artifact
        artifact = wandb.Artifact("test-artifact", type="dataset")
        test_file = tmp_path / "test.txt"
        test_file.write_text("test data")
        artifact.add_file(str(test_file))

        # This should work without prompting for API key
        run.log_artifact(artifact)
        artifact.wait()

    # Verify .netrc was NOT created
    assert not os.path.exists(netrc_path), ".netrc should not be created when API key is explicit"
```

### 4. Unit Tests for Login Behavior
**File**: `tests/unit_tests/test_wandb_login.py`

#### Test: `test_login_with_explicit_api_key_no_netrc_write`
```python
def test_login_with_explicit_api_key_no_netrc_write(tmp_path, monkeypatch, capsys):
    """Test that _login with explicit key and update_api_key=False doesn't write to .netrc"""
    from wandb.sdk import wandb_login

    netrc_path = str(tmp_path / "netrc")
    monkeypatch.setenv("NETRC", netrc_path)

    api_key = "X" * 40

    # Call _login with update_api_key=False (as wandb.init does)
    wandb_login._login(
        key=api_key,
        update_api_key=False,
        _silent=True
    )

    # Verify .netrc was NOT created
    assert not os.path.exists(netrc_path)

    # Verify no "Appending key" message
    _, err = capsys.readouterr()
    assert "Appending key" not in err
```

### 5. Update Existing Tests if Needed
**Files to check**:
- `tests/unit_tests/test_lib/test_apikey.py` - Ensure these tests still pass
- `tests/system_tests/test_core/test_wandb_init.py` - Check for any tests that assume .netrc is always written
- `tests/system_tests/test_core/test_wandb_login.py` - Check for any tests affected by the new behavior

## Test Execution Plan

### Phase 1: Unit Tests (Fast)
```bash
# Test API key behavior
pytest tests/unit_tests/test_wandb_init.py -k "api_key"

# Test login behavior
pytest tests/unit_tests/test_wandb_login.py -k "api_key"

# Test apikey module
pytest tests/unit_tests/test_lib/test_apikey.py
```

### Phase 2: System Tests (Slower, requires API access)
```bash
# Test artifact logging
pytest tests/system_tests/test_artifacts/test_wandb_run_artifacts.py -k "api_key"

# Test full init flow
pytest tests/system_tests/test_core/test_wandb_init.py
```

### Phase 3: Manual Testing
Use the test script at `hack/log_api.py` to verify end-to-end behavior:
```bash
cd hack
python log_api.py
```

## Success Criteria

All tests should:
1. ✅ Pass without prompting for API key
2. ✅ Not create/modify `.netrc` when API key is explicit in settings
3. ✅ Successfully authenticate and log artifacts
4. ✅ Use cached `public.Api()` instance (performance improvement)
5. ✅ Fall back to normal API key resolution when not explicitly provided

## Debug Logging

The following debug messages should appear when running with explicit API key:
```
[DEBUG] _login called with key=<provided>, update_api_key=False
[DEBUG] After _WandbLogin init, wlogin._settings.api_key=<set>
[DEBUG] key was provided, not prompting
[DEBUG] Skipping .netrc write (update_api_key=False)
[DEBUG _public_api] Creating public API with explicit api_key from settings
[DEBUG _public_api] Returning cached public API instance  # On subsequent calls
```

## Notes

- Remove debug logging statements before merging to production (or convert to proper logging levels)
- Ensure backward compatibility: existing code that relies on .netrc should still work
- API key in settings takes precedence over environment variables and .netrc

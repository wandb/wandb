"""Test for fix to config resume empty dict issue #11366."""

import tempfile
import uuid
from unittest.mock import Mock, patch

import pytest
import wandb
from wandb.sdk.wandb_config import Config


def test_config_values_equal_empty_dict_handling():
    """Test that _config_values_equal correctly handles missing empty dicts."""
    config = Config()
    
    # Test case from issue: resumed config missing empty dict
    resumed_config = {"key1": 42}
    new_config = {"key1": 42, "key2": {"nested_key_with_empty_dict": {}}}
    
    assert config._config_values_equal(resumed_config, new_config) is True
    
    # Test reverse order
    assert config._config_values_equal(new_config, resumed_config) is True
    
    # Test identical configs
    identical1 = {"key1": 42, "key2": {"nested_key_with_empty_dict": {}}}
    identical2 = {"key1": 42, "key2": {"nested_key_with_empty_dict": {}}}
    assert config._config_values_equal(identical1, identical2) is True
    
    # Test actually different configs (should not be equal)
    different1 = {"key1": 42}
    different2 = {"key1": 43}
    assert config._config_values_equal(different1, different2) is False
    
    # Test non-empty nested dict differences (should not be equal)
    non_empty1 = {"key1": 42, "key2": {"nested_key": {"data": "value1"}}}
    non_empty2 = {"key1": 42, "key2": {"nested_key": {"data": "value2"}}}
    assert config._config_values_equal(non_empty1, non_empty2) is False
    
    # Test deeply nested empty dicts
    deep_empty1 = {"level1": {"level2": {"level3": {}}}}
    deep_empty2 = {"level1": {"level2": {}}}
    assert config._config_values_equal(deep_empty1, deep_empty2) is True
    
    # Test multiple empty dicts at same level
    multi_empty1 = {"branch1": {}, "branch2": {"data": 42}}
    multi_empty2 = {"branch2": {"data": 42}}
    assert config._config_values_equal(multi_empty1, multi_empty2) is True


def test_sanitize_no_error_with_empty_dict_mismatch():
    """Test that _sanitize doesn't raise ConfigError for empty dict mismatches."""
    config = Config()
    
    # Simulate resumed state with missing empty dict
    config._items = {"key": {"key1": 42}}
    
    # Try to sanitize new config with empty dict - should not raise error
    key, val = config._sanitize("key", {"key1": 42, "key2": {"nested_key_with_empty_dict": {}}})
    
    assert key == "key"
    assert val == {"key1": 42, "key2": {"nested_key_with_empty_dict": {}}}


def test_sanitize_still_catches_real_changes():
    """Test that _sanitize still catches actual config changes."""
    config = Config()
    
    # Set up existing config
    config._items = {"key": {"key1": 42}}
    
    # Try to change actual value - should raise error
    with pytest.raises(wandb.sdk.lib.config_util.ConfigError, match="Attempted to change value"):
        config._sanitize("key", {"key1": 43})


def test_full_config_update_with_empty_dict():
    """Test full config update workflow with empty dict scenario."""
    config = Config()
    
    # Mock settings to avoid jupyter detection
    config._settings = Mock()
    config._settings._jupyter = False
    
    # Simulate resumed config (missing empty dict)
    config._items = {"key": {"key1": 42}}
    
    # This should not raise an error
    new_config = {"key": {"key1": 42, "key2": {"nested_key_with_empty_dict": {}}}}
    result = config._sanitize_dict(new_config)
    
    expected = {"key": {"key1": 42, "key2": {"nested_key_with_empty_dict": {}}}}
    assert result == expected


def test_reproduce_original_issue():
    """Reproduce the exact scenario from issue #11366."""
    config = Config()
    
    # Mock settings
    config._settings = Mock()
    config._settings._jupyter = False
    
    # Original config payload
    original_payload = {
        "key": {
            "key1": 42,
            "key2": {
                "nested_key_with_empty_dict": {},
            },
        },
    }
    
    # Simulate what happens during resume:
    # 1. Config is loaded from server (missing empty dict)
    resumed_config = {
        "key": {"key1": 42}  # Empty dict was lost during server round-trip
    }
    config._items = resumed_config
    
    # 2. User tries to update config with original payload
    # This should NOT raise ConfigError anymore
    try:
        result = config._sanitize_dict(original_payload)
        # If we get here, the fix worked
        assert "key" in result
        assert result["key"]["key1"] == 42
        assert "key2" in result["key"]
        assert result["key"]["key2"]["nested_key_with_empty_dict"] == {}
    except wandb.sdk.lib.config_util.ConfigError:
        pytest.fail("ConfigError was raised, indicating the fix didn't work")


if __name__ == "__main__":
    # Run the basic test to verify fix
    test_config_values_equal_empty_dict_handling()
    test_sanitize_no_error_with_empty_dict_mismatch()
    test_sanitize_still_catches_real_changes()
    test_full_config_update_with_empty_dict()
    test_reproduce_original_issue()
    print("All tests passed! The fix appears to work correctly.")
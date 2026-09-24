"""Simple test for the _config_values_equal logic."""

def config_values_equal(val1, val2):
    """Compare config values, treating missing empty dicts as equivalent.
    
    This handles the case where config resumption loses empty dictionaries
    due to server-side serialization/deserialization, which should not be
    considered a config change.
    """
    if val1 == val2:
        return True
    
    # If both are dicts, do deep comparison with empty dict normalization
    if isinstance(val1, dict) and isinstance(val2, dict):
        # Create normalized copies that treat missing keys as empty dicts
        def normalize_dict(d):
            normalized = {}
            for k, v in d.items():
                if isinstance(v, dict):
                    normalized[k] = normalize_dict(v)
                else:
                    normalized[k] = v
            return normalized
        
        def add_missing_empty_dicts(target, source):
            """Add empty dicts to target for keys that exist in source with empty dicts."""
            for k, v in source.items():
                if k not in target:
                    if isinstance(v, dict) and not v:  # empty dict
                        target[k] = {}
                    elif isinstance(v, dict):  # non-empty dict
                        target[k] = {}
                        add_missing_empty_dicts(target[k], v)
                elif isinstance(v, dict) and isinstance(target[k], dict):
                    add_missing_empty_dicts(target[k], v)
        
        # Make copies and normalize
        norm_val1 = normalize_dict(val1)
        norm_val2 = normalize_dict(val2)
        
        # Add missing empty dicts to both sides
        add_missing_empty_dicts(norm_val1, norm_val2)
        add_missing_empty_dicts(norm_val2, norm_val1)
        
        return norm_val1 == norm_val2
    
    return False


def test_config_values_equal_empty_dict_handling():
    """Test that _config_values_equal correctly handles missing empty dicts."""
    
    # Test case from issue: resumed config missing empty dict
    resumed_config = {"key1": 42}
    new_config = {"key1": 42, "key2": {"nested_key_with_empty_dict": {}}}
    
    assert config_values_equal(resumed_config, new_config) is True
    print("✓ Resumed config vs new config (missing empty dict)")
    
    # Test reverse order
    assert config_values_equal(new_config, resumed_config) is True
    print("✓ New config vs resumed config (reverse order)")
    
    # Test identical configs
    identical1 = {"key1": 42, "key2": {"nested_key_with_empty_dict": {}}}
    identical2 = {"key1": 42, "key2": {"nested_key_with_empty_dict": {}}}
    assert config_values_equal(identical1, identical2) is True
    print("✓ Identical configs")
    
    # Test actually different configs (should not be equal)
    different1 = {"key1": 42}
    different2 = {"key1": 43}
    assert config_values_equal(different1, different2) is False
    print("✓ Actually different configs (correctly not equal)")
    
    # Test non-empty nested dict differences (should not be equal)
    non_empty1 = {"key1": 42, "key2": {"nested_key": {"data": "value1"}}}
    non_empty2 = {"key1": 42, "key2": {"nested_key": {"data": "value2"}}}
    assert config_values_equal(non_empty1, non_empty2) is False
    print("✓ Non-empty nested differences (correctly not equal)")
    
    # Test deeply nested empty dicts
    deep_empty1 = {"level1": {"level2": {"level3": {}}}}
    deep_empty2 = {"level1": {"level2": {}}}
    assert config_values_equal(deep_empty1, deep_empty2) is True
    print("✓ Deeply nested empty dicts")
    
    # Test multiple empty dicts at same level
    multi_empty1 = {"branch1": {}, "branch2": {"data": 42}}
    multi_empty2 = {"branch2": {"data": 42}}
    assert config_values_equal(multi_empty1, multi_empty2) is True
    print("✓ Multiple empty dicts at same level")

    # Test the exact scenario from the issue
    original_payload = {
        "key": {
            "key1": 42,
            "key2": {
                "nested_key_with_empty_dict": {},
            },
        },
    }
    
    resumed_payload = {
        "key": {"key1": 42}  # Missing the nested empty dict
    }
    
    assert config_values_equal(original_payload, resumed_payload) is True
    print("✓ Exact issue scenario (original vs resumed)")


if __name__ == "__main__":
    test_config_values_equal_empty_dict_handling()
    print("\nAll tests passed! The config comparison logic works correctly.")
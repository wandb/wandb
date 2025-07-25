import pytest
from wandb.cli import cli


def test_parse_service_config_valid_single():
    """Test parsing a single valid service configuration."""
    result = cli.parse_service_config(None, None, ["test_service=always"])
    assert result == {"test_service": "always"}


def test_parse_service_config_valid_multiple():
    """Test parsing multiple valid service configurations."""
    result = cli.parse_service_config(None, None, ["service1=always", "service2=never"])
    assert result == {"service1": "always", "service2": "never"}


def test_parse_service_config_empty():
    """Test parsing empty service configurations."""
    result = cli.parse_service_config(None, None, [])
    assert result == {}


def test_parse_service_config_none():
    """Test parsing None service configurations."""
    result = cli.parse_service_config(None, None, None)
    assert result == {}


def test_parse_service_config_invalid_format_no_equals():
    """Test that services without '=' raise an error."""
    with pytest.raises(Exception) as exc_info:
        cli.parse_service_config(None, None, ["invalid_service"])
    assert "Service must be in format 'serviceName=policy'" in str(exc_info.value)


def test_parse_service_config_invalid_format_multiple_equals():
    """Test that services with multiple '=' fail due to invalid policy."""
    with pytest.raises(Exception) as exc_info:
        cli.parse_service_config(None, None, ["service=policy=extra"])
    assert "Policy must be 'always' or 'never', got 'policy=extra'" in str(
        exc_info.value
    )


def test_parse_service_config_empty_service_name():
    """Test that empty service names raise an error."""
    with pytest.raises(Exception) as exc_info:
        cli.parse_service_config(None, None, ["=always"])
    assert "Service name cannot be empty" in str(exc_info.value)


def test_parse_service_config_whitespace_service_name():
    """Test that whitespace-only service names raise an error."""
    with pytest.raises(Exception) as exc_info:
        cli.parse_service_config(None, None, ["   =always"])
    assert "Service name cannot be empty" in str(exc_info.value)


def test_parse_service_config_invalid_policy():
    """Test that invalid policies raise an error."""
    with pytest.raises(Exception) as exc_info:
        cli.parse_service_config(None, None, ["service=invalid"])
    assert "Policy must be 'always' or 'never', got 'invalid'" in str(exc_info.value)


def test_parse_service_config_whitespace_handling():
    """Test that whitespace around service names is stripped."""
    result = cli.parse_service_config(None, None, ["  service_name  =always"])
    assert result == {"service_name": "always"}

    result = cli.parse_service_config(None, None, ["service_name=  always  "])
    assert result == {"service_name": "always"}


def test_service_config_case_sensitivity():
    """Test that policy validation is case-sensitive."""
    with pytest.raises(Exception) as exc_info:
        cli.parse_service_config(None, None, ["service=Always"])
    assert "Policy must be 'always' or 'never'" in str(exc_info.value)

    with pytest.raises(Exception) as exc_info:
        cli.parse_service_config(None, None, ["service=NEVER"])
    assert "Policy must be 'always' or 'never'" in str(exc_info.value)


def test_service_config_duplicate_services():
    """Test that duplicate service names override previous values."""
    result = cli.parse_service_config(None, None, ["service=always", "service=never"])
    assert result == {"service": "never"}  # Last one wins

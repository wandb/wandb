import pytest
from wandb.sdk.lib.wbauth import validation


@pytest.mark.parametrize(
    "key, problems",
    (
        ("", "API key is empty."),
        ("some_prefix-" + "A" * 39, "API key must have 40+ characters, has 39."),
        ("some_prefix-" + "A" * 40, None),
        ("some_prefix-" + "A" * 60, None),
        ("*", "API key may only contain"),
    ),
)
def test_check_api_key(key, problems):
    result = validation.check_api_key(key)

    if problems is None:
        assert result is None
    else:
        assert problems in result

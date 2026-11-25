import pytest
from wandb.sdk.wandb_helper import _to_dict


class FakeLegacyFlags:
    """Minimal stand-in for a legacy TensorFlow FLAGS object."""

    def __init__(self, parsed: bool | None) -> None:
        self.parse_count = 0
        # Use setattr so the names stay dunder and are visible in vars(self).
        setattr(self, "__flags", {"unparsed": "value"})
        if parsed is not None:
            setattr(self, "__parsed", parsed)

    def _parse_flags(self) -> None:
        self.parse_count += 1
        setattr(self, "__flags", {"parsed": "value"})


@pytest.mark.parametrize(
    "parsed, expected_count, expected_dict",
    [
        (True, 0, {"unparsed": "value"}),
        (False, 1, {"parsed": "value"}),
        (None, 1, {"parsed": "value"}),
    ],
    ids=["parsed-true", "parsed-false", "parsed-absent"],
)
def test_to_dict_respects_legacy_flags_parsed_value(
    parsed, expected_count, expected_dict
):
    flags = FakeLegacyFlags(parsed)

    assert _to_dict(flags) == expected_dict
    assert flags.parse_count == expected_count

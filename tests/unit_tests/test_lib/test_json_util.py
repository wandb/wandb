"""Consistency tests for `wandb.sdk.lib.json_util`.

The wrapper delegates to `pydantic_core` for speed but must remain
behaviorally consistent with stdlib `json` for the patterns we use:
basic types, custom encoders, fallbacks, and NaN/Infinity preservation.
"""

from __future__ import annotations

import io
import json
import math

import pytest
from wandb.sdk.lib import json_util

# Payloads that should round-trip and produce data identical to stdlib json.
_PAYLOADS: list[object] = [
    None,
    True,
    False,
    0,
    -1,
    1234567890,
    0.0,
    -3.14,
    1e100,
    "",
    "hello",
    "café 北京 🙂",  # non-ASCII
    [],
    {},
    [1, "two", 3.0, None, True, False],
    {"a": 1, "b": "two", "c": None, "d": [1, 2, 3]},
    {"nested": {"list": [{"k": "v"}, 1, None]}},
]


@pytest.mark.parametrize("payload", _PAYLOADS)
def test_dumps_round_trips(payload: object) -> None:
    """`loads(dumps(x))` reproduces `x` for representative inputs."""
    assert json_util.loads(json_util.dumps(payload)) == payload


@pytest.mark.parametrize("payload", _PAYLOADS)
def test_dumps_parses_to_same_data_as_stdlib(payload: object) -> None:
    """The output decodes to the same Python value as stdlib's output.

    Byte-for-byte equality is not asserted: pydantic_core emits compact JSON
    (no spaces after `,` or `:`) while stdlib defaults to spaces. Data
    equivalence is what matters for our consumers.
    """
    via_wrapper = json.loads(json_util.dumps(payload))
    via_stdlib = json.loads(json.dumps(payload))
    assert via_wrapper == via_stdlib


_NONFINITE = [
    pytest.param(float("nan"), "NaN", id="nan"),
    pytest.param(float("inf"), "Infinity", id="+inf"),
    pytest.param(float("-inf"), "-Infinity", id="-inf"),
]


@pytest.mark.parametrize("value, literal", _NONFINITE)
def test_dumps_nonfinite_float_consistent_with_stdlib(
    value: float, literal: str
) -> None:
    """Wrapper and stdlib both round-trip non-finite floats via the JS literal.

    Whitespace varies between serializers, so this checks behavior rather than
    exact bytes: the literal token appears in both outputs, and parsing either
    output via stdlib `json.loads` produces the same Python float.
    """
    wrapper_out = json_util.dumps({"x": value})
    stdlib_out = json.dumps({"x": value})

    # Both contain the bareword literal (the spacing around it differs).
    assert literal in wrapper_out
    assert literal in stdlib_out

    # And both round-trip to the same Python float (NaN compared via isnan).
    wrapper_x = json.loads(wrapper_out)["x"]
    stdlib_x = json.loads(stdlib_out)["x"]
    if math.isnan(value):
        assert math.isnan(wrapper_x) and math.isnan(stdlib_x)
    else:
        assert wrapper_x == stdlib_x == value


@pytest.mark.parametrize("value, literal", _NONFINITE)
def test_loads_accepts_nonfinite_literal_like_stdlib(
    value: float, literal: str
) -> None:
    """Both decoders accept the bareword tokens and produce equal Python floats."""
    wrapper_decoded = json_util.loads(literal)
    stdlib_decoded = json.loads(literal)
    if math.isnan(value):
        assert math.isnan(wrapper_decoded)
        assert math.isnan(stdlib_decoded)
    else:
        assert wrapper_decoded == stdlib_decoded == value


def test_nonfinite_cross_compatibility() -> None:
    """Each side can read the other's output and produce equal floats."""
    payload = {"nan": float("nan"), "inf": float("inf"), "ninf": float("-inf")}

    wrapper_out = json_util.dumps(payload)
    stdlib_out = json.dumps(payload)

    for decoded in (json.loads(wrapper_out), json_util.loads(stdlib_out)):
        assert math.isnan(decoded["nan"])
        assert decoded["inf"] == float("inf")
        assert decoded["ninf"] == float("-inf")


def test_nonfinite_floats_preserved_in_nested_structures() -> None:
    """NaN/Inf survive nesting inside dicts and lists."""
    payload = {
        "items": [float("nan"), 1.0, float("inf"), {"deep": float("-inf")}],
        "scalar": float("nan"),
    }
    decoded = json_util.loads(json_util.dumps(payload))
    assert math.isnan(decoded["items"][0])
    assert decoded["items"][1] == 1.0
    assert decoded["items"][2] == float("inf")
    assert decoded["items"][3]["deep"] == float("-inf")
    assert math.isnan(decoded["scalar"])


def test_dumps_does_not_coerce_nonfinite_to_null() -> None:
    encoded = json_util.dumps({"nan": float("nan"), "inf": float("inf")})
    assert "null" not in encoded


def test_dumps_coerces_non_string_keys() -> None:
    """Integer keys are stringified, matching stdlib behavior."""
    assert json.loads(json_util.dumps({1: "one", 2: "two"})) == {
        "1": "one",
        "2": "two",
    }


def test_dumps_with_default_callback() -> None:
    """A `default=` callable handles otherwise-unserializable types."""

    class Custom:
        def __init__(self, x: int) -> None:
            self.x = x

    def serialize(obj: object) -> object:
        if isinstance(obj, Custom):
            return {"x": obj.x}
        raise TypeError(obj)

    encoded = json_util.dumps({"item": Custom(42)}, default=serialize)
    assert json.loads(encoded) == {"item": {"x": 42}}


def test_dumps_with_cls_encoder() -> None:
    """A `cls=` encoder's `default` is used as the fallback."""

    class SortedSetEncoder(json.JSONEncoder):
        def default(self, obj: object) -> object:
            if isinstance(obj, set):
                return sorted(obj)
            return super().default(obj)

    encoded = json_util.dumps({"items": {3, 1, 2}}, cls=SortedSetEncoder)
    assert json.loads(encoded) == {"items": [1, 2, 3]}


def test_dumps_default_wins_over_cls() -> None:
    """Matches stdlib precedence: `default=` takes precedence over `cls=`."""

    class CustomEncoder(json.JSONEncoder):
        def default(self, obj: object) -> object:
            return "from-cls"

    def default(obj: object) -> object:
        return "from-default"

    class Unknown:
        pass

    encoded = json_util.dumps({"x": Unknown()}, cls=CustomEncoder, default=default)
    assert json.loads(encoded) == {"x": "from-default"}


def test_dumps_with_indent_produces_pretty_output() -> None:
    """`indent=` formats the JSON across lines and round-trips."""
    payload = {"a": 1, "b": [2, 3]}
    encoded = json_util.dumps(payload, indent=2)
    assert "\n" in encoded
    assert json.loads(encoded) == payload


def test_dumps_falls_back_to_stdlib_for_unsupported_types() -> None:
    """Unsupported types without a fallback raise (same as stdlib).

    The wrapper first tries pydantic_core, which raises on unknown types,
    then re-tries via stdlib `json.dumps` which also raises. The final
    exception is what stdlib would have produced.
    """

    class Unknown:
        pass

    with pytest.raises(TypeError):
        json_util.dumps({"x": Unknown()})


def test_loads_basic() -> None:
    assert json_util.loads('{"a":[1,2,3]}') == {"a": [1, 2, 3]}


@pytest.mark.parametrize(
    "encoded",
    [
        "null",
        "true",
        "false",
        "0",
        "-1",
        "3.14",
        '"hello"',
        "[]",
        "{}",
        "[1, 2, 3]",
        '{"a": 1, "b": [2, 3]}',
        '{"nested": {"x": null}}',
    ],
)
def test_loads_consistent_with_stdlib(encoded: str) -> None:
    """`loads(s)` returns the same Python value as `json.loads(s)`."""
    assert json_util.loads(encoded) == json.loads(encoded)


def test_dump_writes_to_text_fp() -> None:
    fp = io.StringIO()
    json_util.dump({"x": 1}, fp)
    assert json.loads(fp.getvalue()) == {"x": 1}


def test_load_reads_from_text_fp() -> None:
    fp = io.StringIO('{"y": 2}')
    assert json_util.load(fp) == {"y": 2}

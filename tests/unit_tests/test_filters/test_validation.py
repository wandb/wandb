from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any

from pydantic import TypeAdapter, ValidationError
from pytest import mark, param, raises
from wandb._filters import FilterValidator
from wandb._pydantic import FilterDict

VALID_FIELDS = ("tag", "created_at", "updated_at", "metadata")
INVALID_FIELD1 = "bogus"
INVALID_FIELD2 = "also_bogus"

ALIASED_FIELDS = {
    "tag": "tag",
    "tags": "tag",
    "created_at": "created_at",
    "updated_at": "updated_at",
    "metadata": "metadata",
    "artifact_metadata": "metadata",
}

FILTER_ADAPTER = TypeAdapter(Annotated[FilterDict, FilterValidator(VALID_FIELDS)])
ALIASED_ADAPTER = TypeAdapter(Annotated[FilterDict, FilterValidator(ALIASED_FIELDS)])
TRANSFORM_ADAPTER = TypeAdapter(
    Annotated[
        FilterDict,
        FilterValidator(ALIASED_FIELDS, transforms={"tag": str.upper}),
    ]
)


@mark.parametrize(
    "filters",
    [
        param({}, id="empty"),
        param({"tag": "prod"}, id="implicit-eq"),
        param({"tag": ["prod", "staging"]}, id="list-valued-equality"),
        param({"tag": {"$eq": "prod"}}, id="explicit-eq"),
        param({"metadata.foo": 1}, id="dotted-subkey"),
        param({"metadata": {"foo": {"bar": 1}}}, id="nested-subdocument"),
        param({"$and": [{"tag": "x"}, {"created_at": 1}]}, id="and"),
        param({"$or": [{"tag": "x"}, {"created_at": 1}]}, id="or"),
        param({"$nor": [{"tag": "x"}, {"created_at": 1}]}, id="nor"),
        param({"$not": {"tag": "x"}}, id="not"),
        param({"$and": []}, id="empty-and"),
        param({"$or": []}, id="empty-or"),
        param({"$or": [{}]}, id="empty-or-child"),
        param({"$not": {}}, id="empty-not"),
        param(
            {"tag": {"$unknownOp": {INVALID_FIELD1: 1}}},
            id="opaque-field-op",
        ),
        param(
            {"$unknownOp": {INVALID_FIELD1: 1}, "tag": "prod"},
            id="opaque-root-op",
        ),
        param(
            {
                "$and": [
                    {"$unknownOp": {INVALID_FIELD1: 1}},
                    {"$or": [{"created_at": 1}, {"updated_at": 2}]},
                ]
            },
            id="nested-logical-operators",
        ),
    ],
)
def test_valid_filter_unchanged(filters: dict[str, Any]):
    original = deepcopy(filters)

    assert FILTER_ADAPTER.validate_python(filters) == original
    assert filters == original


@mark.parametrize(
    ("orig", "expected"),
    [
        param(
            {
                "$and": [
                    {"artifact_metadata.owner": "alice"},
                    {"metadata.promoted": True},
                    {"$not": {"artifact_metadata.team": "ml"}},
                ]
            },
            {
                "$and": [
                    {"metadata.owner": "alice"},
                    {"metadata.promoted": True},
                    {"$not": {"metadata.team": "ml"}},
                ]
            },
            id="logical-fields",
        ),
        param(
            {"artifact_metadata": [{"artifact_metadata.inner": "not a filter field"}]},
            {"metadata": [{"artifact_metadata.inner": "not a filter field"}]},
            id="opaque-field-operand",
        ),
        param(
            {
                "$unknownOp": {INVALID_FIELD1: 1, "artifact_metadata.owner": "opaque"},
                "artifact_metadata.owner": "alice",
            },
            {
                "$unknownOp": {INVALID_FIELD1: 1, "artifact_metadata.owner": "opaque"},
                "metadata.owner": "alice",
            },
            id="opaque-unknown-operator-operand",
        ),
    ],
)
def test_filter_validator_maps_aliases(orig: dict[str, Any], expected: dict[str, Any]):
    orig_copy = deepcopy(orig)

    assert ALIASED_ADAPTER.validate_python(orig) == expected
    assert orig == orig_copy


def test_filter_validator_transforms_canonicalized_fields():
    orig = {"$or": [{"tags": "prod"}, {"tag": "staging"}]}
    expected = {"$or": [{"tag": "PROD"}, {"tag": "STAGING"}]}

    orig_copy = deepcopy(orig)

    assert TRANSFORM_ADAPTER.validate_python(orig) == expected
    assert orig == orig_copy


@mark.parametrize(
    "raw",
    [
        param(
            {"metadata": 1, "artifact_metadata": 2},
            id="canonical-name-first",
        ),
        param(
            {"artifact_metadata": 1, "metadata": 2},
            id="alias-first",
        ),
        param(
            {"$or": [{"metadata.owner": 1, "artifact_metadata.owner": 2}]},
            id="nested-dotted-fields",
        ),
        param(
            {
                "$or": [
                    {"tag": "prod", "tags": "OOPS"},  # Collision happens here
                    {"metadata": "irrelevant"},
                ]
            },
            id="nested-collision-canonical-first",
        ),
        param(
            {
                "$or": [
                    {"metadata": "irrelevant"},
                    {"tags": "OOPS", "tag": "prod"},  # Collision happens here
                ]
            },
            id="nested-collision-alias-first",
        ),
    ],
)
def test_filter_validator_rejects_runtime_collisions(raw: dict[str, Any]):
    with raises(ValidationError, match=r"(?i)duplicate fields"):
        ALIASED_ADAPTER.validate_python(raw)


@mark.parametrize(
    "filters",
    [
        param({INVALID_FIELD1: 1}, id="root"),
        param({"$and": [{"tag": "x"}, {INVALID_FIELD1: 1}]}, id="and-child"),
        param({"$or": [{"tag": "x"}, {INVALID_FIELD1: 1}]}, id="or-child"),
        param({"$not": {INVALID_FIELD1: 1}}, id="not-child"),
        param(
            {
                "$and": [
                    {"tag": "x"},
                    {"$or": [{"created_at": 1}, {INVALID_FIELD1: 2}]},
                ]
            },
            id="nested-logical-child",
        ),
    ],
)
def test_invalid_filter_field_raises(filters: dict[str, Any]):
    with raises(ValidationError, match="Invalid filter field"):
        FILTER_ADAPTER.validate_python(filters)


def test_invalid_filter_fields_are_all_reported():
    with raises(
        ValidationError,
        match=rf"Invalid filter fields: {INVALID_FIELD2!r}, {INVALID_FIELD1!r}",
    ):
        FILTER_ADAPTER.validate_python({INVALID_FIELD1: 1, INVALID_FIELD2: 2})


@mark.parametrize(
    "filters",
    [
        param({"$and": {"tag": "x"}}, id="variadic-op-requires-list"),
        param({"$or": [1]}, id="logical-child-requires-dict"),
        param({"$not": []}, id="not-requires-dict"),
    ],
)
def test_malformed_logical_operator_raises(filters: dict[str, Any]):
    with raises(ValidationError):
        FILTER_ADAPTER.validate_python(filters)

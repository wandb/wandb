from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any

from pydantic import BaseModel, TypeAdapter, ValidationError
from pytest import mark, param, raises
from wandb._filters import FilterFieldMapper, FilterValidator
from wandb._pydantic import FilterDict

VALID_FIELDS = ("tag", "created_at", "updated_at", "metadata")
INVALID_FIELD = "bogus"

FIELD_ALIASES = {
    "tag": "tag",
    "created_at": "created_at",
    "updated_at": "updated_at",
    "metadata": "metadata",
    "artifact_metadata": "metadata",
}


class ExampleVars(BaseModel):
    filters: Annotated[FilterDict, FilterValidator(VALID_FIELDS)]


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
        param({"tag": {"$future": {INVALID_FIELD: 1}}}, id="opaque-field-op"),
        param(
            {"$future": {INVALID_FIELD: 1}, "tag": "prod"},
            id="opaque-root-op",
        ),
        param(
            {
                "$and": [
                    {"$future": {INVALID_FIELD: 1}},
                    {"$or": [{"created_at": 1}, {"updated_at": 2}]},
                ]
            },
            id="nested-logical-operators",
        ),
    ],
)
def test_valid_filter_unchanged(filters: dict[str, Any]):
    original = deepcopy(filters)

    assert ExampleVars(filters=filters).filters == original
    assert filters == original


def test_filter_validator_maps_aliases_in_annotated_field():
    adapter = TypeAdapter(
        Annotated[FilterDict, FilterValidator(valid=FIELD_ALIASES)]
    )
    raw = {
        "$and": [
            {"artifact_metadata.owner": "alice"},
            {
                "$or": [
                    {"tag": "prod"},
                    {"$not": {"artifact_metadata.team": "ml"}},
                ]
            },
            {"$nor": [{"created_at": 1}]},
        ]
    }

    assert adapter.validate_python(raw) == {
        "$and": [
            {"metadata.owner": "alice"},
            {
                "$or": [
                    {"tag": "prod"},
                    {"$not": {"metadata.team": "ml"}},
                ]
            },
            {"$nor": [{"created_at": 1}]},
        ]
    }


def test_filter_field_mapper_leaves_operands_opaque():
    mapper = FilterFieldMapper(FIELD_ALIASES)
    field_operand = [{"artifact_metadata.owner": "data, not a filter field"}]
    unknown_operator_operand = {
        INVALID_FIELD: 1,
        "artifact_metadata.owner": "also opaque",
    }

    assert mapper(
        {
            "artifact_metadata": field_operand,
            "$future": unknown_operator_operand,
        }
    ) == {
        "metadata": field_operand,
        "$future": unknown_operator_operand,
    }


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
            {"$or": [{"tag": "prod"}], "field": 1},
            id="operator-first",
        ),
        param(
            {"field": 1, "$or": [{"tag": "prod"}]},
            id="mapped-field-first",
        ),
    ],
)
def test_filter_field_mapper_rejects_collisions(raw: dict[str, Any]):
    aliases = {**FIELD_ALIASES, "field": "$or"}

    with raises(ValueError, match="mapping collision"):
        FilterFieldMapper(aliases)(raw)


@mark.parametrize(
    "filters",
    [
        param({INVALID_FIELD: 1}, id="root"),
        param({"$and": [{"tag": "x"}, {INVALID_FIELD: 1}]}, id="logical-child"),
        param({"$not": {INVALID_FIELD: 1}}, id="not-child"),
        param(
            {
                "$and": [
                    {"tag": "x"},
                    {"$or": [{"created_at": 1}, {INVALID_FIELD: 2}]},
                ]
            },
            id="nested-logical-child",
        ),
    ],
)
def test_invalid_filter_field_raises(filters: dict[str, Any]):
    with raises(ValidationError, match="Invalid filter field"):
        ExampleVars(filters=filters)


@mark.parametrize(
    "filters",
    [
        param({"$and": {"tag": "x"}}, id="variadic-op-requires-list"),
        param({"$or": [{}]}, id="logical-child-requires-nonempty-dict"),
        param({"$not": {}}, id="not-requires-nonempty-dict"),
    ],
)
def test_malformed_logical_operator_raises(filters: dict[str, Any]):
    with raises(ValidationError, match=r"must contain|must be"):
        ExampleVars(filters=filters)

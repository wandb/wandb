from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ValidationError
from pytest import mark, param, raises
from wandb._filters import FilterArg


class _TestVars(BaseModel):
    filters: Annotated[
        dict[str, Any],
        AfterValidator(
            FilterArg(allowed=("tag", "created_at", "updated_at", "metadata"))
        ),
    ]


@mark.parametrize(
    "filters",
    [
        param(
            {"tag": "prod"},
            id="valid-implicit-eq",
        ),
        param(
            {"tag": {"$eq": "prod"}},
            id="valid-explicit-eq",
        ),
        param(
            {"tag": {"$regex": "prod"}},
            id="valid-regex",
        ),
        param(
            {"metadata.foo": 1},
            id="valid-dotted-subkey",
        ),
        param(
            {"metadata": {"foo": {"bar": 1}}},
            id="valid-nested-subdoc",
        ),
        param(
            {"$or": [{"tag": "x"}, {"created_at": 1}]},
            id="valid-or-predicate",
        ),
        param(
            {"$and": [{"tag": "x"}, {"created_at": 1}]},
            id="valid-and-predicate",
        ),
        param(
            {"tag": {"$unknownOp": 1}},
            id="valid-inner-unknown-operator",
        ),
        param(
            {"$unknownOp": {"ignored": 1}},
            id="valid-root-unknown-operator",
        ),
        param(
            {
                "$and": [
                    {"tag": "x"},
                    {"$or": [{"created_at": 1}, {"updated_at": 2}]},
                ]
            },
            id="valid-nested-logical-op",
        ),
        param(
            {
                "$or": [{"tag": "x"}, {"created_at": 1}],
                "metadata": {"foo": "bar"},
            },
            id="valid-mixed-root-predicates",
        ),
        param(
            {},
            id="valid-empty",
        ),
    ],
)
def test_valid_filter_returned_unchanged(filters: dict[str, Any]):
    expected = deepcopy(filters)
    assert expected == _TestVars(filters=filters).filters


@mark.parametrize(
    "filters",
    [
        param(
            {"bogus": 1},
            id="invalid-root-field",
        ),
        param(
            {"$and": [{"tag": "x"}, {"nope": 1}]},
            id="invalid-inside-and",
        ),
        param(
            {"$or": [{"tag": "x"}, {"nope": 1}]},
            id="invalid-inside-or",
        ),
        param(
            {"$nor": [{"tag": "x"}, {"nope": 1}]},
            id="invalid-inside-nor",
        ),
        param(
            {"$not": {"nope": 1}},
            id="invalid-inside-not",
        ),
        param(
            {
                "$and": [
                    {"tag": "x"},
                    {"$or": [{"created_at": 1}, {"nope": 2}]},
                ]
            },
            id="invalid-inside-nested-predicates",
        ),
        param(
            {"$and": {"tag": "x"}},
            id="invalid-root-logical-op-shape",
        ),
        param(
            {
                "$unknownOp": {"ignored": 1},
                "tag": "prod",
            },
            id="invalid-mixed-root-predicates",
        ),
    ],
)
def test_unknown_field_raises(filters: dict[str, Any]):
    with raises(ValidationError):
        _TestVars(filters=filters)

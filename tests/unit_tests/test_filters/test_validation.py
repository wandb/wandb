from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any

from pydantic import BaseModel, ValidationError
from pytest import mark, param, raises
from wandb._filters import FilterValidator
from wandb._pydantic import FilterDict

VALID_FIELDS = ("tag", "created_at", "updated_at", "metadata")
"""Fields considered "valid" for these tests."""

INVALID_FIELD = "bogus"
"""Field considered "invalid" for these tests."""


class ExampleVars(BaseModel):
    filters: Annotated[FilterDict, FilterValidator(valid=VALID_FIELDS)]


@mark.parametrize(
    "filters",
    [
        param({}, id="empty"),
        param({"tag": "prod"}, id="implicit-eq"),
        param({"tag": {"$eq": "prod"}}, id="explicit-eq"),
        param({"tag": {"$regex": "prod"}}, id="regex"),
        param({"metadata.foo": 1}, id="dotted-subkey"),
        param({"metadata": {"foo": {"bar": 1}}}, id="nested-subdoc"),
        param({"$or": [{"tag": "x"}, {"created_at": 1}]}, id="or-predicate"),
        param({"$and": [{"tag": "x"}, {"created_at": 1}]}, id="and-predicate"),
        param({"tag": {"$unknownOp": 1}}, id="nested-unknown-operator"),
        param({"$unknownOp": {"ignored": 1}}, id="root-unknown-operator"),
        param(
            {
                "$and": [
                    {"tag": "x"},
                    {"$or": [{"created_at": 1}, {"updated_at": 2}]},
                ]
            },
            id="nested-logical-op",
        ),
        param(
            {
                "$or": [{"tag": "x"}, {"created_at": 1}],
                "metadata": {"foo": "bar"},
            },
            id="known-mixed-root-predicates",
        ),
        param(
            {
                "$unknownOp": {"ignored": 1},
                "tag": "prod",
            },
            marks=mark.xfail(
                reason="Needs to be fixed, fields inside $unknownOp should be ignored",
                strict=True,
            ),
            id="unknown-mixed-root-predicates",
        ),
    ],
)
def test_valid_filter_unchanged(filters: dict[str, Any]):
    orig = deepcopy(filters)
    assert orig == ExampleVars(filters=filters).filters


@mark.parametrize(
    "filters",
    [
        param({INVALID_FIELD: 1}, id="root-field"),
        param({"$and": [{"tag": "x"}, {INVALID_FIELD: 1}]}, id="inside-and"),
        param({"$or": [{"tag": "x"}, {INVALID_FIELD: 1}]}, id="inside-or"),
        param({"$nor": [{"tag": "x"}, {INVALID_FIELD: 1}]}, id="inside-nor"),
        param({"$not": {INVALID_FIELD: 1}}, id="inside-not"),
        param(
            {
                "$and": [
                    {"tag": "x"},
                    {"$or": [{"created_at": 1}, {INVALID_FIELD: 2}]},
                ]
            },
            id="inside-nested-predicates",
        ),
        param({"$and": {"tag": "x"}}, id="bad-and-op-shape"),
        param({"$or": {"tag": "x"}}, id="bad-or-op-shape"),
    ],
)
def test_invalid_filter_raises(filters: dict[str, Any]):
    with raises(ValidationError):
        ExampleVars(filters=filters)

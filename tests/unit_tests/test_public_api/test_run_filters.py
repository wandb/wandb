from typing import Any

import pytest
from wandb.apis.public.run_filters import validate_run_filters


@pytest.mark.parametrize("invalid_leaf", [False, True])
def test_validate_run_filters_handles_nested_groups(invalid_leaf: bool) -> None:
    depth = 50
    filters: dict[str, Any] = {"tags": {"$all": [["sgd"]] if invalid_leaf else ["sgd"]}}
    for _ in range(depth):
        filters = {"$and": [filters]}

    if invalid_leaf:
        with pytest.raises(ValueError) as exc_info:
            validate_run_filters(filters)
        expected_path = "filters" + ".$and[0]" * depth + ".tags.$all[0]"
        assert str(exc_info.value) == (
            f"{expected_path}: expected a tag string, got list"
        )
    else:
        assert validate_run_filters(filters) is filters


def test_validate_run_filters_handles_wide_groups() -> None:
    filters = {"$or": [{"tags": {"$in": ["sgd"]}} for _ in range(10_000)]}

    assert validate_run_filters(filters) is filters


@pytest.mark.parametrize(
    "children,error_path",
    [
        (
            [
                {"$or": [{"tags": {"$all": [["sgd"]]}}]},
                {"$in": ["group-1"]},
            ],
            "filters.$and[0].$or[0].tags.$all[0]",
        ),
        (
            [
                {"$or": [{"tags": {"$all": ["sgd"]}}]},
                {"$in": ["group-1"]},
            ],
            "filters.$and[1].$in",
        ),
        (
            [{"$or": [{"tags": {"$all": ["sgd"]}}]}],
            "filters.$nin",
        ),
    ],
)
def test_validate_run_filters_reports_first_error_in_depth_first_order(
    children: list[dict[str, Any]], error_path: str
) -> None:
    filters = {"$and": children, "$nin": ["group-2"]}

    with pytest.raises(ValueError) as exc_info:
        validate_run_filters(filters)

    assert str(exc_info.value).startswith(f"{error_path}:")


def test_validate_run_filters_accepts_shared_subtrees() -> None:
    shared = {"$or": [{"tags": {"$all": ["sgd"]}}]}
    filters = {"$and": [shared, {"$nor": [shared]}, shared]}

    assert validate_run_filters(filters) is filters


def test_validate_run_filters_reports_error_after_shared_subtree() -> None:
    shared = {"$or": [{"tags": ["sgd"]}]}
    filters = {"$and": [shared, shared, {"tags": [["test"]]}]}

    with pytest.raises(ValueError) as exc_info:
        validate_run_filters(filters)

    assert str(exc_info.value) == (
        "filters.$and[2].tags[0]: expected a tag string, got list"
    )


def test_validate_run_filters_rechecks_changed_filters() -> None:
    shared: dict[str, Any] = {"tags": ["sgd"]}
    filters = {"$and": [shared, shared]}
    assert validate_run_filters(filters) is filters

    shared["tags"] = [["sgd"]]

    with pytest.raises(ValueError) as exc_info:
        validate_run_filters(filters)

    assert str(exc_info.value) == (
        "filters.$and[0].tags[0]: expected a tag string, got list"
    )

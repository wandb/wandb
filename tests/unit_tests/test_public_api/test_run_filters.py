import pytest
from wandb.apis.public.run_filters import validate_run_filters


def test_validate_run_filters_defaults_none_to_empty() -> None:
    assert validate_run_filters(None) == {}


@pytest.mark.parametrize(
    "filters",
    [
        {"$and": [{"tags": {"$all": ["sgd"]}}]},
        {"group": {"$in": [["group-1"]]}},
    ],
)
def test_validate_run_filters_accepts_valid_filters(filters) -> None:
    assert validate_run_filters(filters) is filters


@pytest.mark.parametrize(
    "filters,error_path",
    [
        ({"tags": {"$all": [["sgd"], "test"]}}, r"filters\.tags\.\$all\[0\]"),
        (
            {"$and": [{"tags": {"$all": [["sgd"]]}}]},
            r"filters\.\$and\[0\]\.tags\.\$all\[0\]",
        ),
        ({"tags": {"$all": "sgd"}}, r"filters\.tags\.\$all"),
        ({"tags": [["sgd"]]}, r"filters\.tags\[0\]"),
        ({"$in": ["group-1"]}, r"filters\.\$in"),
        ([], r"^filters:"),
    ],
)
def test_validate_run_filters_rejects_invalid_filters(filters, error_path) -> None:
    with pytest.raises(ValueError, match=error_path):
        validate_run_filters(filters)

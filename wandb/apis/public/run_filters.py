"""Validation for run query filters."""

from __future__ import annotations

from typing import Any, NoReturn

_LOGICAL_OPERATORS = frozenset({"$and", "$or", "$nor"})
_MEMBERSHIP_OPERATORS = frozenset({"$all", "$in", "$nin"})


def validate_run_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    """Check logical groups and tag lists in run filters.

    Other fields and operators are left to the server to validate.

    Args:
        filters: Filters to check, or `None` for no filtering.

    Returns:
        The input dictionary unchanged, or an empty dictionary for `None`.

    Raises:
        ValueError: If a checked filter is malformed.
    """
    filters = {} if filters is None else filters
    _validate_query(filters, [])
    return filters


def _validate_query(query: object, filter_path: list[str]) -> None:
    if not isinstance(query, dict):
        _raise_filter_error(filter_path, "", "expected a filter dictionary")

    for field, condition in query.items():
        if field in _LOGICAL_OPERATORS:
            if not isinstance(condition, (list, tuple)):
                _raise_filter_error(
                    filter_path, f".{field}", "expected a list of filter dictionaries"
                )
            for index, child in enumerate(condition):
                filter_path.append(f".{field}[{index}]")
                _validate_query(child, filter_path)
                filter_path.pop()
        elif field in _MEMBERSHIP_OPERATORS:
            _raise_filter_error(
                filter_path,
                f".{field}",
                f"{field} must be nested under a field name; "
                f"for example, {{'tags': {{'{field}': ['tag-1']}}}}",
            )
        elif field == "tags":
            _validate_tags(condition, filter_path)


def _validate_tags(condition: object, filter_path: list[str]) -> None:
    """Check tag operands, which the server accepts only as strings.

    Membership (`{"tags": {"$all": [...]}}`) and direct equality
    (`{"tags": [...]}`) are both checked: a non-string in either form fails
    server-side with an opaque error instead of a useful one.
    """
    if isinstance(condition, dict):
        for operator, values in condition.items():
            if operator not in _MEMBERSHIP_OPERATORS:
                continue
            _validate_tag_values(values, filter_path, f".tags.{operator}")
    elif isinstance(condition, (list, tuple)):
        _validate_tag_values(condition, filter_path, ".tags")


def _validate_tag_values(values: object, filter_path: list[str], suffix: str) -> None:
    if not isinstance(values, (list, tuple)):
        _raise_filter_error(filter_path, suffix, "expected a list of tag strings")
    for index, value in enumerate(values):
        if not isinstance(value, str):
            _raise_filter_error(
                filter_path,
                f"{suffix}[{index}]",
                f"expected a tag string, got {type(value).__name__}",
            )


def _raise_filter_error(filter_path: list[str], suffix: str, message: str) -> NoReturn:
    # Prefix the offending location with the public argument's name.
    raise ValueError(f"filters{''.join(filter_path)}{suffix}: {message}")

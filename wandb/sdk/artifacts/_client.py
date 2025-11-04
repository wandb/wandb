from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence, TypeVar

from wandb._iterutils import PathLookupError, get_path
from wandb._pydantic import GQLResult

if TYPE_CHECKING:
    from pydantic import ValidationError
    from wandb_graphql.language.ast import Document

    from wandb.apis.public import RetryingClient
    from wandb.errors import ResponseError

ResultT = TypeVar("ResultT", bound=GQLResult)


def validated_execute(
    client: RetryingClient,
    op: Document,
    variables: dict[str, Any] | None = None,
    *,
    result_path: Sequence[int | str] | None = None,
    result_cls: type[ResultT],
) -> ResultT:
    """Execute a GraphQL operation and validate the response data."""
    data = client.execute(op, variable_values=variables)
    return parse_result(data, path=result_path, cls=result_cls)


def parse_result(
    data: Any,
    *,
    cls: type[ResultT],
    path: Sequence[int | str] | None = None,
) -> ResultT:
    try:
        data = get_path(data, path=path) if path else data
        result = cls.model_validate(data)
    except (PathLookupError, ValidationError) as e:
        msg = f"Error on parsing response data: {e}"
        raise ResponseError(msg) from e
    else:
        return result

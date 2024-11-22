from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, TypeVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from wandb.apis.public import ArtifactCollection, Project
    from wandb.sdk.automations.scopes import _Scope

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


def pydantic_isinstance(v: Any, cls: type[BaseModelT]) -> bool:
    """Return True if the value can be validated (parsed) as a Pydantic type."""
    # Underlying implementation should be in Rust,
    # so may be preferable to `try...except ValidationError`
    # https://docs.pydantic.dev/latest/api/pydantic_core/#pydantic_core.SchemaValidator.isinstance_python
    return cls.__pydantic_validator__.isinstance_python(v)


def uppercase_if_str(v: Any) -> Any:
    """Uppercase the value if it is a string."""
    return v.upper() if isinstance(v, str) else v


# Maps MongoDB comparison operators -> Python literal (str) representations
_MONGO2PY_OPS: Final[dict[str, str]] = {
    "$eq": "==",
    "$ne": "!=",
    "$gt": ">",
    "$lt": "<",
    "$gte": ">=",
    "$lte": "<=",
}
# Reverse mapping from Python literal (str) -> MongoDB operator key
PY2MONGO_OPS: Final[dict[str, str]] = {v: k for k, v in _MONGO2PY_OPS.items()}


def mongo_op_to_python(op: str) -> str:
    """Convert a MongoDB op key to its Python (str) representation."""
    return op if (op in PY2MONGO_OPS) else _MONGO2PY_OPS[op]


def python_op_to_mongo(op: str) -> str:
    """Convert a Python (str) comparison operator to its MongoDB op key."""
    return op if (op in _MONGO2PY_OPS) else PY2MONGO_OPS[op]


def validate_scope(v: ArtifactCollection | Project | _Scope) -> _Scope:
    """Convert a familiar wandb `Project` or `ArtifactCollection` object to an automation scope."""
    from wandb.apis.public import ArtifactCollection, Project

    from .scopes import ArtifactCollectionScope, ProjectScope

    if isinstance(v, Project):
        return ProjectScope(id=v.id, name=v.name)
    if isinstance(v, ArtifactCollection):
        return ArtifactCollectionScope(id=v.id, name=v.name)
    return v

from __future__ import annotations

from typing import Any, Final

from .filters import Eq, Gt, Gte, Lt, Lte, Ne


def uppercase_if_str(v: Any) -> Any:
    """Convert a string to uppercase if it is a string."""
    return v.upper() if isinstance(v, str) else v


_MONGO2PYTHON_OPS: Final[dict[str, str]] = {
    Eq.OP: "==",
    Ne.OP: "!=",
    Gt.OP: ">",
    Lt.OP: "<",
    Gte.OP: ">=",
    Lte.OP: "<=",
}
_PYTHON2MONGO_OPS: Final[dict[str, str]] = {v: k for k, v in _MONGO2PYTHON_OPS.items()}


def mongo_op_to_python(op: str) -> str:
    """Convert a MongoDB op key to its Python (str) representation."""
    return op if (op in _PYTHON2MONGO_OPS) else _MONGO2PYTHON_OPS[op]


def python_op_to_mongo(op: str) -> str:
    """Convert a Python (str) comparison operator to its MongoDB op key."""
    return op if (op in _MONGO2PYTHON_OPS) else _PYTHON2MONGO_OPS[op]

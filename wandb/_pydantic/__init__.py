"""Internal utilities for working with pydantic."""

from .base import Base, GQLBase, GQLId, SerializedToJson, Typename

__all__ = [
    "Base",
    "GQLBase",
    "Typename",
    "GQLId",
    "SerializedToJson",
]

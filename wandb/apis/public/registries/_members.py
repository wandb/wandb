"""Types and helpers for managing registry members."""

from __future__ import annotations

from base64 import b64decode, b64encode
from collections import defaultdict
from enum import Enum
from functools import singledispatchmethod
from typing import Iterable, Literal, Union

from pydantic.dataclasses import dataclass as pydantic_dataclass

from wandb._pydantic import GQLBase
from wandb._strutils import nameof

from ..teams import Team
from ..users import User


class MemberKind(str, Enum):
    """Identifies what kind of object a registry member is."""

    USER = "User"
    ENTITY = "Entity"


class MemberRole(str, Enum):
    """Identifies the role of a member."""

    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    RESTRICTED_VIEWER = "restricted_viewer"


class UserMember(GQLBase, arbitrary_types_allowed=True):
    kind: Literal[MemberKind.USER] = MemberKind.USER

    user: User
    role: Union[MemberRole, str]  # noqa: UP007


class TeamMember(GQLBase, arbitrary_types_allowed=True):
    kind: Literal[MemberKind.ENTITY] = MemberKind.ENTITY

    team: Team
    role: Union[MemberRole, str]  # noqa: UP007


MemberOrId = Union[User, Team, UserMember, TeamMember, str]
"""Type hint for a registry member argument that accepts a User, Team, or their ID."""


def parse_member_ids(members: Iterable[MemberOrId]) -> tuple[list[str], list[str]]:
    """Returns a tuple of (user_ids, team_ids) from parsing the given objects."""
    ids_by_kind: dict[MemberKind, set[str]] = defaultdict(set)

    for parsed in map(MemberId.from_obj, members):
        ids_by_kind[parsed.kind].add(parsed.encode())

    user_ids = ids_by_kind[MemberKind.USER]
    team_ids = ids_by_kind[MemberKind.ENTITY]

    # Ordering shouldn't matter, but sort anyway for reproducibility and testing
    return sorted(user_ids), sorted(team_ids)


@pydantic_dataclass
class MemberId:
    kind: MemberKind
    id: int

    def encode(self) -> str:
        """Converts this parsed ID to a string (base64-encoded) GraphQL ID."""
        return b64encode(f"{self.kind.value}:{self.id}".encode("ascii")).decode("ascii")

    @singledispatchmethod
    @classmethod
    def from_obj(cls, obj: MemberOrId, /) -> MemberId:
        """Parses `User` or `Team` ID from the argument."""
        # Fallback for unexpected types
        raise TypeError(
            f"Member arg must be a {nameof(User)!r}, {nameof(Team)!r}, or a user/team ID. "
            f"Got: {nameof(type(obj))!r}"
        )

    @from_obj.register(User)
    @from_obj.register(Team)
    @classmethod
    def _from_obj_with_id(cls, obj: User | Team, /) -> MemberId:
        # Use the object's string (base64-encoded) GraphQL ID
        return cls._from_id(obj.id)

    @from_obj.register(UserMember)
    @classmethod
    def _from_user_member(cls, member: UserMember, /) -> MemberId:
        return cls._from_id(member.user.id)

    @from_obj.register(TeamMember)
    @classmethod
    def _from_team_member(cls, member: TeamMember, /) -> MemberId:
        return cls._from_id(member.team.id)

    @from_obj.register(str)
    @classmethod
    def _from_id(cls, id_: str, /) -> MemberId:
        # Parse the ID to figure out if it's a team or user ID
        str_kind, str_idx = b64decode(id_).decode("ascii").split(":", maxsplit=1)
        try:
            kind = MemberKind(str_kind)
        except ValueError:
            raise ValueError(f"{id_!r} is not a W&B Entity or User ID") from None
        else:
            return cls(kind, str_idx)

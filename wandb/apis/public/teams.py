"""W&B Public API for managing teams and team members.

This module provides classes for managing W&B teams and their members.

Note:
    This module is part of the W&B Public API and provides methods to manage
    teams and their members. Team management operations require appropriate
    permissions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from typing_extensions import Self
from wandb_gql import gql

from wandb.apis.attrs import Attrs

if TYPE_CHECKING:
    from .api import Api, RetryingClient


class Member(Attrs):
    """A member of a team.

    Args:
        client (`wandb.apis.internal.Api`): The client instance to use
        team (str): The name of the team this member belongs to
        attrs (dict): The member attributes
    """

    def __init__(self, client: RetryingClient, team: str, attrs: Mapping[str, Any]):
        super().__init__(attrs)
        self._client = client
        self.team = team

    def delete(self):
        """Remove a member from a team.

        Returns:
            Boolean indicating success
        """
        from requests import HTTPError

        from wandb.apis._generated import DELETE_INVITE_GQL, DeleteInvite

        try:
            data = self._client.execute(
                gql(DELETE_INVITE_GQL), {"id": self.id, "entity": self.team}
            )
        except HTTPError:
            return False
        else:
            result = DeleteInvite.model_validate(data).result
            return (result is not None) and result.success

    def __repr__(self):
        return f"<Member {self.name} ({self.account_type})>"


class Team(Attrs):
    """A class that represents a W&B team.

    This class provides methods to manage W&B teams, including creating teams,
    inviting members, and managing service accounts. It inherits from Attrs
    to handle team attributes.

    Args:
        client (`wandb.apis.public.Api`): The api instance to use
        name (str): The name of the team
        attrs (dict): Optional dictionary of team attributes

    Note:
        Team management requires appropriate permissions.
    """

    def __init__(
        self,
        client: RetryingClient,
        name: str,
        attrs: Mapping[str, Any] | None = None,
    ):
        super().__init__(attrs or {})
        self._client = client
        self.name = name
        self.load()

    @classmethod
    def create(cls, api: Api, team: str, admin_username: str | None = None) -> Self:
        """Create a new team.

        Args:
            api: (`Api`) The api instance to use
            team: (str) The name of the team
            admin_username: (str) optional username of the admin user of the team, defaults to the current user.

        Returns:
            A `Team` object
        """
        from requests import HTTPError

        from wandb.apis._generated import CREATE_TEAM_GQL

        try:
            api.client.execute(
                gql(CREATE_TEAM_GQL),
                {"teamName": team, "teamAdminUserName": admin_username},
            )
        except HTTPError:
            pass
        return cls(api.client, team)

    def invite(self, username_or_email: str, admin: bool = False) -> bool:
        """Invite a user to a team.

        Args:
            username_or_email: (str) The username or email address of the user
                you want to invite.
            admin: (bool) Whether to make this user a team admin.
                Defaults to `False`.

        Returns:
            `True` on success, `False` if user was already invited or didn't exist.
        """
        from requests import HTTPError

        from wandb.apis._generated import CREATE_INVITE_GQL

        variables = {
            "entity": self.name,
            "admin": admin,
            ("email" if ("@" in username_or_email) else "username"): username_or_email,
        }
        try:
            self._client.execute(gql(CREATE_INVITE_GQL), variables)
        except HTTPError:
            return False
        return True

    def create_service_account(self, description: str) -> Member | None:
        """Create a service account for the team.

        Args:
            description: (str) A description for this service account

        Returns:
            The service account `Member` object, or None on failure
        """
        from requests import HTTPError

        from wandb.apis._generated import CREATE_SERVICE_ACCOUNT_GQL

        try:
            self._client.execute(
                gql(CREATE_SERVICE_ACCOUNT_GQL),
                {"entity": self.name, "description": description},
            )
            self.load(True)
            return self.members[-1]
        except HTTPError:
            return None

    def load(self, force: bool = False) -> dict[str, Any]:
        """Return members that belong to a team.

        <!-- lazydoc-ignore: internal -->
        """
        from wandb.apis._generated import GET_TEAM_ENTITY_GQL, GetTeamEntity

        if force or not self._attrs:
            data = self._client.execute(gql(GET_TEAM_ENTITY_GQL), {"name": self.name})
            result = GetTeamEntity.model_validate(data)
            self._attrs = entity.model_dump() if (entity := result.entity) else {}
            self._attrs["members"] = [
                Member(self._client, self.name, member)
                for member in self._attrs["members"]
            ]
        return self._attrs

    def __repr__(self) -> str:
        return f"<Team {self.name}>"

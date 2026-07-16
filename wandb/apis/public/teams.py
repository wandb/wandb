"""W&B Public API for managing teams and team members.

This module provides classes for managing W&B teams and their members.

Note:
    This module is part of the W&B Public API and provides methods to manage
    teams and their members. Team management operations require appropriate
    permissions.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from wandb.apis.attrs import Attrs
from wandb.sdk.lib.service.service_connection import WandbApiFailedError

if TYPE_CHECKING:
    from .api import Api
    from .service_api import ServiceApi


class Member(Attrs):
    """A member of a team.

    Args:
        service_api: The service API instance to use for querying W&B.
        team (str): The name of the team this member belongs to
        attrs (dict): The member attributes
    """

    def __init__(self, service_api: ServiceApi, team: str, attrs: Mapping[str, Any]):
        super().__init__(attrs)
        self._service_api = service_api
        self.team = team

    def delete(self):
        """Remove a member from a team.

        Returns:
            Boolean indicating success
        """
        from wandb.apis._generated import DELETE_INVITE_GQL, DeleteInvite

        try:
            data = self._service_api.execute_graphql(
                DELETE_INVITE_GQL,
                {"id": self.id, "entity": self.team},
                parse=DeleteInvite.model_validate_json,
            )
        except WandbApiFailedError:
            return False
        else:
            return ((result := data.result) is not None) and result.success

    def __repr__(self):
        return f"<Member {self.name} ({self.account_type})>"


class Team(Attrs):
    """A class that represents a W&B team.

    This class provides methods to manage W&B teams, including creating teams,
    inviting members, and managing service accounts. It inherits from Attrs
    to handle team attributes.

    Args:
        service_api: The service API instance to use for querying W&B.
        name (str): The name of the team
        attrs (dict): Optional dictionary of team attributes

    Note:
        Do not instantiate this class directly. Use `wandb.Api().team()` to
        look up an existing team, or `wandb.Api().create_team()` to create a
        new one. Team management requires appropriate permissions.

    Examples:
    Look up a team and invite a member.

    ```python
    import wandb

    api = wandb.Api()
    team = api.team("my-team")
    team.invite("user@example.com")
    ```

    Create a team and add a service account.

    ```python
    import wandb

    api = wandb.Api()
    team = api.create_team("my-team")
    team.create_service_account("CI service account")
    ```
    """

    def __init__(
        self,
        service_api: ServiceApi,
        name: str,
        attrs: Mapping[str, Any] | None = None,
    ):
        super().__init__(attrs or {})
        self._service_api = service_api
        self.name = name
        self.load()

    @classmethod
    def create(cls, api: Api, team: str, admin_username: str | None = None) -> Team:
        """Create a new team.

        Args:
            api: (`Api`) The api instance to use
            team: (str) The name of the team
            admin_username: (str) optional username of the admin user of the team, defaults to the current user.

        Returns:
            A `Team` object
        """
        from wandb.apis._generated import CREATE_TEAM_GQL

        try:
            api._service_api.execute_graphql(
                CREATE_TEAM_GQL,
                {"teamName": team, "teamAdminUserName": admin_username},
            )
        except WandbApiFailedError:
            pass
        return cls(api._service_api, team)

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
        from wandb.apis._generated import CREATE_INVITE_GQL

        variables = {
            "entity": self.name,
            "admin": admin,
            ("email" if ("@" in username_or_email) else "username"): username_or_email,
        }
        try:
            self._service_api.execute_graphql(CREATE_INVITE_GQL, variables)
        except WandbApiFailedError:
            return False
        return True

    def create_service_account(self, description: str) -> Member | None:
        """Create a service account for the team.

        Args:
            description: (str) A description for this service account

        Returns:
            The service account `Member` object, or None on failure
        """
        from wandb.apis._generated import CREATE_SERVICE_ACCOUNT_GQL

        try:
            self._service_api.execute_graphql(
                CREATE_SERVICE_ACCOUNT_GQL,
                {"entity": self.name, "description": description},
            )
            self.load(True)
            return self.members[-1]
        except WandbApiFailedError:
            return None

    def load(self, force: bool = False) -> dict[str, Any]:
        """Return members that belong to a team.

        <!-- lazydoc-ignore: internal -->
        """
        from wandb.apis._generated import GET_TEAM_ENTITY_GQL, GetTeamEntity

        if force or not self._attrs:
            result = self._service_api.execute_graphql(
                GET_TEAM_ENTITY_GQL,
                variables={"name": self.name},
                parse=GetTeamEntity.model_validate_json,
            )
            self._attrs = entity.model_dump() if (entity := result.entity) else {}
            self._attrs["members"] = [
                Member(self._service_api, self.name, member)
                for member in self._attrs["members"]
            ]
        return self._attrs

    def __repr__(self) -> str:
        return f"<Team {self.name}>"

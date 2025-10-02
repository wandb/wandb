"""W&B Public API for managing teams and team members.

This module provides classes for managing W&B teams and their members.

Note:
    This module is part of the W&B Public API and provides methods to manage
    teams and their members. Team management operations require appropriate
    permissions.
"""

from __future__ import annotations

import requests
from wandb_gql import gql

from wandb.apis.attrs import Attrs


class Member(Attrs):
    """A member of a team.

    Args:
        client (`wandb.apis.internal.Api`): The client instance to use
        team (str): The name of the team this member belongs to
        attrs (dict): The member attributes
    """

    DELETE_MEMBER_MUTATION = gql(
        """
    mutation DeleteInvite($id: String, $entityName: String) {
        deleteInvite(input: {id: $id, entityName: $entityName}) {
            success
        }
    }
  """
    )

    def __init__(self, client, team, attrs):
        super().__init__(attrs)
        self._client = client
        self.team = team

    def delete(self):
        """Remove a member from a team.

        Returns:
            Boolean indicating success
        """
        try:
            return self._client.execute(
                self.DELETE_MEMBER_MUTATION, {"id": self.id, "entityName": self.team}
            )["deleteInvite"]["success"]
        except requests.exceptions.HTTPError:
            return False

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

    CREATE_TEAM_MUTATION = gql(
        """
    mutation CreateTeam($teamName: String!, $teamAdminUserName: String) {
        createTeam(input: {teamName: $teamName, teamAdminUserName: $teamAdminUserName}) {
            entity {
                id
                name
                available
                photoUrl
                limits
            }
        }
    }
    """
    )
    CREATE_INVITE_MUTATION = gql(
        """
    mutation CreateInvite($entityName: String!, $email: String, $username: String, $admin: Boolean) {
        createInvite(input: {entityName: $entityName, email: $email, username: $username, admin: $admin}) {
            invite {
                id
                name
                email
                createdAt
                toUser {
                    name
                }
            }
        }
    }
    """
    )
    TEAM_QUERY = gql(
        """
    query Entity($name: String!) {
        entity(name: $name) {
            id
            name
            available
            photoUrl
            readOnly
            readOnlyAdmin
            isTeam
            privateOnly
            storageBytes
            codeSavingEnabled
            defaultAccess
            isPaid
            members {
                id
                admin
                pending
                email
                username
                name
                photoUrl
                accountType
                apiKey
            }
        }
    }
    """
    )
    CREATE_SERVICE_ACCOUNT_MUTATION = gql(
        """
    mutation CreateServiceAccount($entityName: String!, $description: String!) {
        createServiceAccount(
            input: {description: $description, entityName: $entityName}
        ) {
            user {
                id
            }
        }
    }
    """
    )

    def __init__(self, client, name, attrs=None):
        super().__init__(attrs or {})
        self._client = client
        self.name = name
        self.load()

    @classmethod
    def create(cls, api, team, admin_username=None):
        """Create a new team.

        Args:
            api: (`Api`) The api instance to use
            team: (str) The name of the team
            admin_username: (str) optional username of the admin user of the team, defaults to the current user.

        Returns:
            A `Team` object
        """
        try:
            api.client.execute(
                cls.CREATE_TEAM_MUTATION,
                {"teamName": team, "teamAdminUserName": admin_username},
            )
        except requests.exceptions.HTTPError:
            pass
        return Team(api.client, team)

    def invite(self, username_or_email, admin=False):
        """Invite a user to a team.

        Args:
            username_or_email: (str) The username or email address of the user
                you want to invite.
            admin: (bool) Whether to make this user a team admin.
                Defaults to `False`.

        Returns:
            `True` on success, `False` if user was already invited or didn't exist.
        """
        variables = {"entityName": self.name, "admin": admin}
        if "@" in username_or_email:
            variables["email"] = username_or_email
        else:
            variables["username"] = username_or_email
        try:
            self._client.execute(self.CREATE_INVITE_MUTATION, variables)
        except requests.exceptions.HTTPError:
            return False
        return True

    def create_service_account(self, description):
        """Create a service account for the team.

        Args:
            description: (str) A description for this service account

        Returns:
            The service account `Member` object, or None on failure
        """
        try:
            self._client.execute(
                self.CREATE_SERVICE_ACCOUNT_MUTATION,
                {"description": description, "entityName": self.name},
            )
            self.load(True)
            return self.members[-1]
        except requests.exceptions.HTTPError:
            return None

    def load(self, force=False):
        """Return members that belong to a team.

        <!-- lazydoc-ignore: internal -->
        """
        if force or not self._attrs:
            response = self._client.execute(self.TEAM_QUERY, {"name": self.name})
            self._attrs = response["entity"]
            self._attrs["members"] = [
                Member(self._client, self.name, member)
                for member in self._attrs["members"]
            ]
        return self._attrs

    def __repr__(self):
        return f"<Team {self.name}>"

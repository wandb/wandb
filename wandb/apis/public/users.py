"""W&B Public API for managing users and API keys.

This module provides classes for managing W&B users and their API keys.

Note:
    This module is part of the W&B Public API and provides methods to manage
    users and their authentication. Some operations require admin privileges.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, MutableMapping

from typing_extensions import Self
from wandb_gql import gql

import wandb
from wandb.apis.attrs import Attrs

if TYPE_CHECKING:
    from .api import Api, RetryingClient


class User(Attrs):
    """A class representing a W&B user with authentication and management capabilities.

    This class provides methods to manage W&B users, including creating users,
    managing API keys, and accessing team memberships. It inherits from Attrs
    to handle user attributes.

    Args:
        client: (`wandb.apis.internal.Api`) The client instance to use
        attrs: (dict) The user attributes

    Note:
        Some operations require admin privileges
    """

    def __init__(self, client: RetryingClient, attrs: MutableMapping[str, Any]):
        super().__init__(attrs)
        self._client = client
        self._user_api: Api | None = None

    @property
    def user_api(self) -> Api | None:
        """An instance of the api using credentials from the user."""
        if self._user_api is None and self.api_keys:
            self._user_api = wandb.Api(api_key=self.api_keys[0])
        return self._user_api

    @classmethod
    def create(cls, api: Api, email: str, admin: bool = False) -> Self:
        """Create a new user.

        Args:
            api (`Api`): The api instance to use
            email (str): The name of the team
            admin (bool): Whether this user should be a global instance admin

        Returns:
            A `User` object
        """
        from wandb.apis._generated import (
            CREATE_USER_FROM_ADMIN_GQL,
            CreateUserFromAdmin,
        )

        gql_op = gql(CREATE_USER_FROM_ADMIN_GQL)
        data = api.client.execute(gql_op, {"email": email, "admin": admin})
        user = CreateUserFromAdmin.model_validate(data).result.user
        return cls(api.client, user.model_dump())

    @property
    def api_keys(self) -> list[str]:
        """List of API key names associated with the user.

        Returns:
            Names of API keys associated with the user. Empty list if user
            has no API keys or if API key data hasn't been loaded.
        """
        if self._attrs.get("apiKeys") is None:
            return []
        return [k["node"]["name"] for k in self._attrs["apiKeys"]["edges"]]

    @property
    def teams(self) -> list[str]:
        """List of team names that the user is a member of.

        Returns:
            Names of teams the user belongs to. Empty list if user has no
            team memberships or if teams data hasn't been loaded.
        """
        if self._attrs.get("teams") is None:
            return []
        return [k["node"]["name"] for k in self._attrs["teams"]["edges"]]

    def delete_api_key(self, api_key: str) -> bool:
        """Delete a user's api key.

        Args:
            api_key (str): The name of the API key to delete. This should be
                one of the names returned by the `api_keys` property.

        Returns:
            Boolean indicating success

        Raises:
            ValueError if the api_key couldn't be found
        """
        from requests import HTTPError

        from wandb.apis._generated import DELETE_API_KEY_GQL

        idx = self.api_keys.index(api_key)
        api_key_id = self._attrs["apiKeys"]["edges"][idx]["node"]["id"]
        try:
            self._client.execute(gql(DELETE_API_KEY_GQL), {"id": api_key_id})
        except HTTPError:
            return False
        return True

    def generate_api_key(self, description: str | None = None) -> str | None:
        """Generate a new api key.

        Args:
            description (str, optional): A description for the new API key. This can be
                used to identify the purpose of the API key.

        Returns:
            The new api key, or None on failure
        """
        from requests import HTTPError

        from wandb.apis._generated import GENERATE_API_KEY_GQL, GenerateApiKey

        try:
            # We must make this call using credentials from the original user
            gql_op = gql(GENERATE_API_KEY_GQL)
            data = self.user_api.client.execute(gql_op, {"description": description})
            key_fragment = GenerateApiKey.model_validate(data).result.api_key
            self._attrs["apiKeys"]["edges"].append({"node": key_fragment.model_dump()})
        except (HTTPError, AttributeError):
            return None
        else:
            return key_fragment.name

    def __repr__(self) -> str:
        if email := self._attrs.get("email"):
            return f"<User {email}>"
        if username := self._attrs.get("username"):
            return f"<User {username}>"
        if id_ := self._attrs.get("id"):
            return f"<User {id_}>"
        if name := self._attrs.get("name"):
            return f"<User {name!r}>"
        return "<User ???>"

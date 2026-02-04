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
    """A user on a W&B instance.

    This allows managing a user's API keys and accessing information like
    team memberships. The `create` class method can be used to create a new
    user.

    Args:
        client: The GraphQL client to use for network operations.
        attrs: A subset of the User type in the GraphQL schema.

    <!-- lazydoc-ignore-init: internal -->
    """

    def __init__(self, client: RetryingClient, attrs: MutableMapping[str, Any]):
        super().__init__(attrs)
        self._client = client
        self._user_api: Api | None = None

    @property
    def user_api(self) -> Api | None:
        """A `wandb.Api` instance using the user's credentials."""
        if self._user_api is None and self.api_keys:
            self._user_api = wandb.Api(api_key=self.api_keys[0])
        return self._user_api

    @classmethod
    def create(cls, api: Api, email: str, admin: bool = False) -> Self:
        """Create a new user.

        This is an internal method. Use the `create_user()` method of
        `wandb.Api` instead.

        Args:
            api: The API instance to use to create the user.
            email: The email for the user.
            admin: Whether this user should be a global instance admin.

        Returns:
            A `User` object.

        <!-- lazydoc-ignore-classmethod: internal -->
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
        """Names of the user's API keys.

        This property returns the names of the the API keys, *not* the secret
        associated with the key. The name of the key cannot be used as an API
        key.

        The list is empty if the user has no API keys or if API keys have not
        been loaded.
        """
        if self._attrs.get("apiKeys") is None:
            return []
        return [k["node"]["name"] for k in self._attrs["apiKeys"]["edges"]]

    @property
    def teams(self) -> list[str]:
        """Names of the user's teams.

        This is an empty list if the user has no team memberships or if teams
        data was not loaded.
        """
        if self._attrs.get("teams") is None:
            return []
        return [k["node"]["name"] for k in self._attrs["teams"]["edges"]]

    def delete_api_key(self, api_key: str) -> bool:
        """Delete a user's API key.

        Only the owner of the key or an admin can delete it.

        Args:
            api_key: The name of the API key to delete. Use one of
                the names returned by the `api_keys` property.

        Returns:
            True on success, false on failure.
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
        """Generate a new API key.

        Args:
            description: A description for the new API key. This can be
                used to identify the purpose of the API key.

        Returns:
            The generated API key (the full secret, not just the name), or
            None on failure.
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

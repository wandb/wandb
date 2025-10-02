"""W&B Public API for managing users and API keys.

This module provides classes for managing W&B users and their API keys.

Note:
    This module is part of the W&B Public API and provides methods to manage
    users and their authentication. Some operations require admin privileges.
"""

from __future__ import annotations

import requests
from wandb_gql import gql

import wandb
from wandb.apis.attrs import Attrs


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

    CREATE_USER_MUTATION = gql(
        """
    mutation CreateUserFromAdmin($email: String!, $admin: Boolean) {
        createUser(input: {email: $email, admin: $admin}) {
            user {
                id
                name
                username
                email
                admin
            }
        }
    }
        """
    )

    DELETE_API_KEY_MUTATION = gql(
        """
    mutation DeleteApiKey($id: String!) {
        deleteApiKey(input: {id: $id}) {
            success
        }
    }
        """
    )
    GENERATE_API_KEY_MUTATION = gql(
        """
    mutation GenerateApiKey($description: String) {
        generateApiKey(input: {description: $description}) {
            apiKey {
                id
                name
            }
        }
    }
        """
    )

    def __init__(self, client, attrs):
        super().__init__(attrs)
        self._client = client
        self._user_api = None

    @property
    def user_api(self):
        """An instance of the api using credentials from the user."""
        if self._user_api is None and len(self.api_keys) > 0:
            self._user_api = wandb.Api(api_key=self.api_keys[0])
        return self._user_api

    @classmethod
    def create(cls, api, email, admin=False):
        """Create a new user.

        Args:
            api (`Api`): The api instance to use
            email (str): The name of the team
            admin (bool): Whether this user should be a global instance admin

        Returns:
            A `User` object
        """
        res = api.client.execute(
            cls.CREATE_USER_MUTATION,
            {"email": email, "admin": admin},
        )
        return User(api.client, res["createUser"]["user"])

    @property
    def api_keys(self):
        """List of API key names associated with the user.

        Returns:
            list[str]: Names of API keys associated with the user. Empty list if user
                has no API keys or if API key data hasn't been loaded.
        """
        if self._attrs.get("apiKeys") is None:
            return []
        return [k["node"]["name"] for k in self._attrs["apiKeys"]["edges"]]

    @property
    def teams(self):
        """List of team names that the user is a member of.

        Returns:
            list (list): Names of teams the user belongs to. Empty list if user has no
                team memberships or if teams data hasn't been loaded.
        """
        if self._attrs.get("teams") is None:
            return []
        return [k["node"]["name"] for k in self._attrs["teams"]["edges"]]

    def delete_api_key(self, api_key):
        """Delete a user's api key.

        Args:
            api_key (str): The name of the API key to delete. This should be
                one of the names returned by the `api_keys` property.

        Returns:
            Boolean indicating success

        Raises:
            ValueError if the api_key couldn't be found
        """
        idx = self.api_keys.index(api_key)
        try:
            self._client.execute(
                self.DELETE_API_KEY_MUTATION,
                {"id": self._attrs["apiKeys"]["edges"][idx]["node"]["id"]},
            )
        except requests.exceptions.HTTPError:
            return False
        return True

    def generate_api_key(self, description=None):
        """Generate a new api key.

        Args:
            description (str, optional): A description for the new API key. This can be
                used to identify the purpose of the API key.

        Returns:
            The new api key, or None on failure
        """
        try:
            # We must make this call using credentials from the original user
            key = self.user_api.client.execute(
                self.GENERATE_API_KEY_MUTATION, {"description": description}
            )["generateApiKey"]["apiKey"]
            self._attrs["apiKeys"]["edges"].append({"node": key})
            return key["name"]
        except (requests.exceptions.HTTPError, AttributeError):
            return None

    def __repr__(self):
        if "email" in self._attrs:
            return f"<User {self._attrs['email']}>"
        elif "username" in self._attrs:
            return f"<User {self._attrs['username']}>"
        elif "id" in self._attrs:
            return f"<User {self._attrs['id']}>"
        elif "name" in self._attrs:
            return f"<User {self._attrs['name']!r}>"
        else:
            return "<User ???>"

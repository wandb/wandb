"""Public API: users."""
import requests
from wandb_gql import gql

import wandb
from wandb.apis.attrs import Attrs


class User(Attrs):
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
    DISABLE_USER_MUTATION = gql(
        """
    mutation DeleteUser($id: ID!) {
        deleteUser(input: {id: $id}) {
            user {
            id
            }
        }
    }
  """
    )
    ENABLE_USER_MUTATION = gql(
        """
    mutation UndeleteUser($id: ID!) {
        undeleteUser(input: {id: $id}) {
            user {
            id
            }
        }
    }
  """
    )
    PURGE_USER_MUTATION = gql(
        """
    mutation PurgeUser($username: String!, $email: String!) {
        purgeUser(input: {username: $username, email: $email}) {
            user {
            id
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

        Arguments:
            api: (`Api`) The api instance to use
            email: (str) The email of the user
            admin: (bool) Whether this user should be a global instance admin

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
        if self._attrs.get("apiKeys") is None:
            return []
        return [k["node"]["name"] for k in self._attrs["apiKeys"]["edges"]]

    @property
    def teams(self):
        if self._attrs.get("teams") is None:
            return []
        return [k["node"]["name"] for k in self._attrs["teams"]["edges"]]

    def delete_api_key(self, api_key):
        """Delete a user's api key.

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

    def disable(self):
        """Disable a user from local instance.

        Returns:
            Boolean indicating success
        """
        try:
            response = self._client.execute(
                self.DISABLE_USER_MUTATION, {"id": self.id}
            )
            if response is None: return False
            success = bool(response.get('deleteUser', {}).get('user', {}).get('id'))
            status = "Successfully" if success else "Failed to"
            print(f"{status} disabled '{self.username}' from instance.")
            return success
        except Exception as e:
            print(f"An error occurred while disabling the user {self.username}: {e}")
            return None
        
    def enable(self):
        """Re-enable user on local instance.

        Returns:
            Boolean indicating success
        """
        try:
            response = self._client.execute(
                self.ENABLE_USER_MUTATION, {"id": self.id}
            )
            if response is None: return False
            success = bool(response.get('undeleteUser', {}).get('user', {}).get('id'))
            status = "Successfully" if success else "Failed to"
            print(f"{status} re-enabled '{self.username}' on instance.")
            return success
        except Exception as e:
            print(f"An error occurred while re-enabling the user {self.username}: {e}")
            return None

    def purge(self, confirm=False):
        """Remove/Delete user from local instance.

        Note: This function purges the user from the local instance, will permanently delete all user data and is not a reversable action
        
        Args:
            confirm (bool): Must be True to proceed with purging the user.
        
        Returns:
            Boolean indicating success
        """
        if not confirm:
            print("User purge not confirmed. Set confirm=True to proceed.")
            return None
    
        try:
            response = self._client.execute(
                self.PURGE_USER_MUTATION, {"username": self.username, "email": self.email}
            )
            if response is None: return False
            success = bool(response.get('purgeUser', {}).get('user', {}).get('id'))
            status = "Successfully" if success else "Failed to"
            print(f"{status} purged '{self.username}' from instance.")
            return success
        except Exception as e:
            print(f"An error occurred while purging user {self.username}: {e}")
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

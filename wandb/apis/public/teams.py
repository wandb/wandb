"""Public API: teams."""
import requests
from wandb_gql import gql

from wandb.apis.attrs import Attrs


class Member(Attrs):
    DELETE_MEMBER_MUTATION = gql(
        """
    mutation DeleteInvite($id: String, $entityName: String) {
        deleteInvite(input: {id: $id, entityName: $entityName}) {
            success
        }
    }
  """
    )
    DISABLE_MEMBER_MUTATION = gql(
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
    CHECK_TEAM_ORG_ID_QUERY = gql(
        """
    query BasicTeamOrganization($entityName: String) {
        entity(name: $entityName) {
            organization {
            id
            name
            }
        }
    }
  """
    )
    REMOVE_MEMBER_FROM_ORGANIZATION_MUTATION = gql(
        """
    mutation removeUserFromOrganization($userName: String!, $organizationId: ID!) {
        removeUserFromOrganization(input: { userName: $userName, organizationId: $organizationId}){
            success
        }
    }
  """
    )
    def __init__(self, client, team, attrs):
        super().__init__(attrs)
        self._client = client
        self.team = team

    def delete(self, remove_from_org=False):
        """Remove a member from a team.

        Arguments:
            remove_from_org (bool): When set to True, removes the member from the organization. For local server instances, user is disabled.

        Returns:
            Boolean indicating success
        """
        def execute_query(query, variables, operation):
            """Execute a GraphQL request with given variables and return the response."""
            try:
                response = self._client.execute(query, variables)
                return response
            except Exception as e:
                print(f"An error occurred while executing the {operation} request: {e}")
                return None

        def print_requests_status(success, action, target):
            """Prints the request status message."""
            status = "Successfully" if success else "Failed to"
            print(f"{status} {action} '{self.username}' from {target}.")

        def remove_member_from_team():
            """Remove a member from the team."""
            response = execute_query(self.DELETE_MEMBER_MUTATION, {"id": self.id, "entityName": self.team}, "remove from team")
            if response is None: return False
            success = response.get("deleteInvite", {}).get("success", False)
            print_requests_status(success, "removed", f"team '{self.team}'")
            return success

        def remove_member_from_organization():
            """Remove a member from the organization, if applicable."""
            response = execute_query(self.CHECK_TEAM_ORG_ID_QUERY, {"entityName": self.team}, "remove from organization")
            if response is None: return False
            org_data = response.get("entity", {}).get("organization", {})
            if org_data.get("id"):
                response = execute_query(self.REMOVE_MEMBER_FROM_ORGANIZATION_MUTATION, {"userName": self.username, "organizationId": org_data["id"]}, "remove from organization")
                if response is None: return False
                success = response.get("removeUserFromOrganization", {}).get("success", False)
                print_requests_status(success, "removed", f"organization '{org_data.get('name')}'")
                return success
            else:
                print(f"Organization ID not found for team '{self.team}'.")
                return False

        def disable_member():
            """Disable the member from local instance."""
            response = execute_query(self.DISABLE_MEMBER_MUTATION, {"id": self.id}, "disable from organization")
            if response is None: return False
            success = bool(response.get('deleteUser', {}).get('user', {}).get('id'))
            print_requests_status(success, "disabled", "instance")
            return success

        # Start by removing the member from the team
        if not remove_member_from_team():
            return False

        # If requested, attempt to remove the member from the organization or disable the member
        if remove_from_org and self._client.app_url == "https://wandb.ai/":
            return remove_member_from_organization()
        elif not remove_from_org:
            return True  # Success from team removal, no further action required
        else:
            return disable_member()

    def __repr__(self):
        return f"<Member {self.name} ({self.account_type})>"


class Team(Attrs):
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
    DELETE_TEAM_MUTATION = gql(
        """
    mutation DeleteTeam($teamName: String!) {
        deleteTeam(input: {teamName: $teamName}) {
            success
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

        Arguments:
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
    
    @classmethod
    def delete(cls, api, team):
        """Delete a team.

        Arguments:
            api: (`Api`) The api instance to use
            team: (str) The name of the team

        Returns:
            Boolean indicating success
        """
        try:
            api.client.execute(
                cls.DELETE_TEAM_MUTATION,
                {"teamName": team},
            )
            print(f"Successfully deleted team {team}.")
            return True
        except requests.exceptions.HTTPError as e:
            print(f"Failed to delete team {team}. Exception caught: {e}")
            return False
    
    def invite(self, username_or_email, admin=False):
        """Invite a user to a team.

        Arguments:
            username_or_email: (str) The username or email address of the user you want to invite
            admin: (bool) Whether to make this user a team admin, defaults to False

        Returns:
            True on success, False if user was already invited or didn't exist
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

        Arguments:
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

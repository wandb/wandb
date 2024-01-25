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
    REMOVE_USER_ORGANIZATION_QUERY = gql(
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
            remove_from_org (bool): If True, also remove the member from the organization.

        Returns:
            Boolean indicating success
        """
        try:
            delete_response = self._client.execute(
                self.DELETE_MEMBER_MUTATION, {"id": self.id, "entityName": self.team}
            )
            delete_success = delete_response.get("deleteInvite", {}).get("success", False)
            action_status = "Successfully" if delete_success else "Failed to"
            print(f"{action_status} removed user '{self.username}' from team '{self.team}'.")
            if not delete_success or not remove_from_org:
                return delete_success

            org_response = self._client.execute(
                self.CHECK_TEAM_ORG_ID_QUERY, {"entityName": self.team}
            )
            org_data = org_response.get("entity", {}).get("organization", {})
            org_id, org_name = org_data.get("id"), org_data.get("name")
            org_id = org_response.get("entity", {}).get("organization", {}).get("id")

            if org_id:
                remove_org_response = self._client.execute(
                    self.REMOVE_USER_ORGANIZATION_QUERY,
                    {"userName": self.username, "organizationId": org_id}
                )
                remove_org_success = remove_org_response.get("removeUserFromOrganization", {}).get("success", False)
                action_status = "Successfully" if remove_org_success else "Failed to"
                print(f"{action_status} removed user '{self.username}' from organization '{org_name}'.")
                return remove_org_success
            else:
                print(f"Organization ID not found for team '{self.team}'.")
                return False

        except requests.exceptions.HTTPError:
            return False

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
        except requests.exceptions.HTTPError:
            pass
        return True
    
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

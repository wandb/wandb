import gql from 'graphql-tag';

export const USER_QUERY = gql`
  query Viewer {
    viewer {
      id
      admin
      email
      entity
      defaultFramework
      photoUrl
      flags
      teams {
        edges {
          node {
            id
            name
            photoUrl
          }
        }
      }
      apiKeys {
        edges {
          node {
            id
            name
          }
        }
      }
    }
  }
`;

export const USERS_QUERY = gql`
  query Users($name: String) {
    users(name: $name)
  }
`;

export const ENTITY_QUERY = gql`
  query Entity($name: String) {
    entity(name: $name) {
      id
      name
      available
      photoUrl
      members {
        id
        admin
        pending
        username
        name
        email
        accountType
        apiKey
      }
    }
  }
`;

export const CREATE_INVITE = gql`
  mutation CreateInvite(
    $entityName: String!
    $username: String
    $email: String
  ) {
    createInvite(
      input: {username: $username, entityName: $entityName, email: $email}
    ) {
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
`;

export const DELETE_INVITE = gql`
  mutation DeleteInvite($id: String, $entityName: String) {
    deleteInvite(input: {id: $id, entityName: $entityName}) {
      success
    }
  }
`;

export const CREATE_SERVICE_ACCOUNT = gql`
  mutation CreateServiceAccount($entityName: String!, $description: String!) {
    createServiceAccount(
      input: {description: $description, entityName: $entityName}
    ) {
      user {
        id
        name
        apiKeys {
          edges {
            node {
              id
              name
            }
          }
        }
      }
    }
  }
`;

export const CREATE_ENTITY = gql`
  mutation CreateEntity($name: String!, $invited: String, $framework: String) {
    createEntity(
      input: {name: $name, defaultFramework: $framework, invited: $invited}
    ) {
      entity {
        name
        photoUrl
        invitedTeam
      }
      apiKey {
        name
      }
    }
  }
`;

export const USER_MUTATION = gql`
  mutation UpdateUser(
    $defaultEntity: String
    $defaultFramework: String
    $photoUrl: String
  ) {
    updateUser(
      input: {
        defaultEntity: $defaultEntity
        defaultFramework: $defaultFramework
        photoUrl: $photoUrl
      }
    ) {
      user {
        entity
      }
    }
  }
`;

export const API_KEY_MUTATION = gql`
  mutation ApiKeyGen($description: String) {
    generateApiKey(input: {description: $description}) {
      apiKey {
        id
        name
      }
    }
  }
`;

export const API_KEY_DELETION = gql`
  mutation ApiKeyDel($id: String!) {
    deleteApiKey(input: {id: $id}) {
      success
    }
  }
`;

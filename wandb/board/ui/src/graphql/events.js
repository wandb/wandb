import gql from 'graphql-tag';

export const EVENTS_QUERY = gql`
  query Timeline($entityName: String, $admin: Boolean) {
    events(entityName: $entityName, admin: $admin) {
      edges {
        node {
          id
          name
          entityName
          projectName
          description
          state
          kind
          extra
          url
          user {
            name
            username
            photoUrl
          }
          createdAt
        }
      }
    }
  }
`;

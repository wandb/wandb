import gql from 'graphql-tag';

export const JOBS_QUERY = gql`
  query Model(
    $cursor: String
    $name: String!
    $entityName: String
    $limit: Int = 50
  ) {
    model(name: $name, entityName: $entityName) {
      id
      jobs(first: $limit, after: $cursor) {
        edges {
          node {
            id
            type
            repo
            program
            dockerImage
          }
        }
        pageInfo {
          endCursor
          hasNextPage
        }
      }
    }
  }
`;

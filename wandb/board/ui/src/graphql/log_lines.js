import gql from 'graphql-tag';

export const LOGS_QUERY = gql`
  query LogLines(
    $cursor: String
    $run: String!
    $modelName: String
    $entityName: String
  ) {
    model(name: $modelName, entityName: $entityName) {
      id
      bucket(name: $run) {
        id
        logLines(after: $cursor, last: 1000) {
          edges {
            node {
              id
              line
              level
            }
          }
        }
      }
    }
  }
`;

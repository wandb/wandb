import gql from 'graphql-tag';

export const FILTER_KEY_SUGGESTIONS = gql`
  query FilterSuggestions(
    $name: String!
    $entityName: String
    $filters: JSONString
  ) {
    project(name: $name, entityName: $entityName) {
      id
      name
      pathCounts(filters: $filters)
    }
  }
`;

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

export const FILTER_VALUE_SUGGESTIONS = gql`
  query FilterValueSuggestions(
    $name: String!
    $entityName: String
    $keyPath: String
    $filters: JSONString
  ) {
    project(name: $name, entityName: $entityName) {
      id
      name
      valueCounts(keyPath: $keyPath, filters: $filters)
    }
  }
`;

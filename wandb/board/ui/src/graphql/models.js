import gql from 'graphql-tag';
import {fragments as runFragments} from './runs';

export const MODEL_QUERY = gql`
  query Model(
    $name: String!
    $logCursor: String
    $entityName: String
    $bucketName: String!
    $upload: Boolean
    $detailed: Boolean!
    $requestSubscribe: Boolean = false
  ) {
    project(name: $name, entityName: $entityName) {
      id
      name
      entityName
      description
      createdAt
      bucketCount
      access
      summaryMetrics
      run(name: $bucketName) {
        id
        name
        __typename
        ...SelectRunFragment
        ...BasicRunFragment
        ...DetailedRunFragment @include(if: $detailed)
        requestSubscribe @include(if: $requestSubscribe)
      }
      views
    }
    viewer {
      id
      email
      photoUrl
      admin
      defaultFramework
    }
  }
  ${runFragments.selectRun}
  ${runFragments.basicRun}
  ${runFragments.detailedRun}
`;

export const MODEL_UPSERT = gql`
  mutation upsertModel(
    $description: String
    $entityName: String!
    $id: String
    $name: String!
    $framework: String
    $access: String
    $views: JSONString
  ) {
    upsertModel(
      input: {
        description: $description
        entityName: $entityName
        id: $id
        name: $name
        framework: $framework
        access: $access
        views: $views
      }
    ) {
      project {
        id
        name
        entityName
        description
        access
        views
      }
      model {
        id
        name
        entityName
        description
        access
        views
      }
      inserted
    }
  }
`;

export const MODEL_DELETION = gql`
  mutation deleteModel($id: String!) {
    deleteModel(input: {id: $id}) {
      success
    }
  }
`;

export const MODELS_QUERY = gql`
  query Models($cursor: String, $entityName: String) {
    models(first: 300, after: $cursor, entityName: $entityName) {
      edges {
        node {
          id
          name
          entityName
          description
        }
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
    viewer {
      id
      email
      photoUrl
    }
  }
`;

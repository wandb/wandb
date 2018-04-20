import gql from 'graphql-tag';

export const fragments = {
  basicRun: gql`
    fragment BasicRunFragment on Run {
      id
      name
      config
      framework
      description
      createdAt
      heartbeatAt
      github
      commit
      host
      state
      shouldStop
      sweep {
        name
      }
      summaryMetrics
      systemMetrics
      user {
        username
        photoUrl
      }
      tags
    }
  `,
  detailedRun: gql`
    fragment DetailedRunFragment on Run {
      id
      history
      events
      exampleTableColumns
      exampleTableTypes
      exampleTable
      fileCount
      logLines(after: $logCursor, last: 1000) {
        edges {
          node {
            id
            line
            level
          }
        }
      }
      files {
        edges {
          node {
            id
            name
            url(upload: $upload)
            sizeBytes
            updatedAt
          }
        }
      }
    }
  `,
  historyRun: gql`
    fragment HistoryRunFragment on Run {
      history(samples: 500)
    }
  `,
};

export const RUNS_QUERY = gql`
  query ModelRuns(
    $cursor: String
    $name: String!
    $entityName: String
    $jobKey: String
    $order: String
    $filters: JSONString
    $limit: Int = 500
    $bucketIds: [String]
    $history: Boolean = false
    $requestSubscribe: Boolean!
  ) {
    project(name: $name, entityName: $entityName) {
      id
      name
      createdAt
      entityName
      description
      summaryMetrics
      views
      requestSubscribe @include(if: $requestSubscribe)
      runs(
        first: $limit
        after: $cursor
        jobKey: $jobKey
        order: $order
        names: $bucketIds
        filters: $filters
      ) {
        paths
        edges {
          node {
            ...BasicRunFragment
            ...HistoryRunFragment @include(if: $history)
            user {
              username
              photoUrl
            }
          }
        }
        pageInfo {
          startCursor
          hasPreviousPage
          endCursor
          hasNextPage
        }
      }
    }
    viewer {
      id
      email
      photoUrl
      admin
    }
  }
  ${fragments.basicRun}
  ${fragments.historyRun}
`;

export const PROJECT_QUERY = gql`
  query Project(
    $name: String!
    $entityName: String
    $filters: JSONString
    $selections: JSONString
  ) {
    project(name: $name, entityName: $entityName) {
      id
      name
      createdAt
      entityName
      description
      views
      requestSubscribe
      runCount(filters: {})
      filteredCount: runCount(filters: $filters)
      selectedCount: runCount(filters: $selections)
    }
  }
`;

export const RUN_UPSERT = gql`
  mutation upsertRun($id: String, $description: String, $tags: [String!]) {
    upsertBucket(input: {id: $id, description: $description, tags: $tags}) {
      bucket {
        id
        name
        description
        tags
      }
      inserted
    }
  }
`;

export const MODIFY_RUNS = gql`
  mutation modifyRuns($ids: [String], $addTags: [String]) {
    modifyRuns(input: {ids: $ids, addTags: $addTags}) {
      runs {
        ...BasicRunFragment
        user {
          username
          photoUrl
        }
      }
    }
  }
  ${fragments.basicRun}
`;

export const RUN_DELETION = gql`
  mutation deleteBucket($id: String!) {
    deleteBucket(input: {id: $id}) {
      success
    }
  }
`;

export const RUN_STOP = gql`
  mutation stopRun($id: String!) {
    stopRun(input: {id: $id}) {
      success
    }
  }
`;

export const LAUNCH_RUN = gql`
  mutation launchRun(
    $id: String!
    $image: String!
    $command: String
    $datasets: [String]
  ) {
    launchRun(
      input: {id: $id, image: $image, command: $command, datasets: $datasets}
    ) {
      podName
      status
    }
  }
`;

export const HISTORY_QUERY = gql`
  query RunHistory($name: String!, $entityName: String, $bucketIds: [String]) {
    project(name: $name, entityName: $entityName) {
      id
      runs(first: 10000, names: $bucketIds) {
        edges {
          node {
            id
            ...HistoryRunFragment
          }
        }
      }
    }
  }
  ${fragments.historyRun}
`;

export const FAKE_HISTORY_QUERY = gql`
  query FakeRunHistory($histQueryKey: String!) {
    project(key: $histQueryKey) {
      id
      runs {
        edges {
          node {
            id
            name
            ...HistoryRunFragment
          }
        }
      }
    }
  }
  ${fragments.historyRun}
`;

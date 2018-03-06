import gql from 'graphql-tag';

export const fragments = {
  basicRun: gql`
    fragment BasicRunFragment on BucketType {
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
    fragment DetailedRunFragment on BucketType {
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
    fragment HistoryRunFragment on BucketType {
      history
    }
  `,
  // This is not actually stored on the server, we manually write/read from the cache to track
  // it's loading state.
  historyRunLoading: gql`
    fragment HistoryRunLoadingFragment on BucketType {
      historyLoading
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
    $limit: Int = 1000
    $bucketIds: [String]
    $history: Boolean = false
  ) {
    model(name: $name, entityName: $entityName) {
      id
      name
      createdAt
      entityName
      description
      summaryMetrics
      views
      sweeps {
        edges {
          node {
            id
            name
            createdAt
            heartbeatAt
            updatedAt
            description
            state
            runCount
            user {
              username
              photoUrl
            }
          }
        }
      }
      buckets(
        first: $limit
        after: $cursor
        jobKey: $jobKey
        order: $order
        names: $bucketIds
      ) {
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
    model(name: $name, entityName: $entityName) {
      id
      buckets(first: 10000, names: $bucketIds) {
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
    model(key: $histQueryKey) {
      id
      buckets {
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

import gql from 'graphql-tag';

export const fragments = {
  basicRun: gql`
    fragment BasicRunFragment on Run {
      framework
      description
      createdAt
      heartbeatAt
      github
      commit
      host
      state
      shouldStop
      groupCounts
      sweep {
        name
      }
      user {
        username
        photoUrl
      }
      tags
    }
  `,
  detailedRun: gql`
    fragment DetailedRunFragment on Run {
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
  selectRun: gql`
    fragment SelectRunFragment on Run {
      config
      summaryMetrics
      systemMetrics
    }
  `,
  historyRun: gql`
    fragment HistoryRunFragment on Run {
      history(samples: 500)
    }
  `,
};

// Some weirdness here. If a fragment is disabled by a skip/include directive,
// quiver/graphene will remove the fields in the fragment. Order matters, whatever
// the last fragment to be included/skipped says goes. We must include __typename
// above fragments or it ends up getting removed.
export const RUNS_QUERY = gql`
  query ModelRuns(
    $cursor: String
    $name: String!
    $entityName: String
    $jobKey: String
    $order: String
    $filters: JSONString
    $limit: Int = 1000
    $bucketIds: [String]
    $requestSubscribe: Boolean!
    $selectEnable: Boolean = true
    $basicEnable: Boolean = true
    $history: Boolean = false
    $fields: [String]
    $historyFields: [String]
    $groupKeys: [String]
    $groupLevel: Int
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
      runCount(filters: $filters)
      runs(
        first: $limit
        after: $cursor
        jobKey: $jobKey
        order: $order
        names: $bucketIds
        filters: $filters
        fields: $fields
        historyFields: $historyFields
        groupKeys: $groupKeys
        groupLevel: $groupLevel
      ) {
        paths
        edges {
          node {
            id
            name
            __typename
            ...SelectRunFragment @include(if: $selectEnable)
            ...BasicRunFragment @include(if: $basicEnable)
            ...HistoryRunFragment @include(if: $history)
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
  ${fragments.selectRun}
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
      runCount(filters: "{}")
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
  mutation modifyRuns(
    $filters: JSONString
    $entityName: String
    $projectName: String
    $addTags: [String]
  ) {
    modifyRuns(
      input: {
        filters: $filters
        entityName: $entityName
        projectName: $projectName
        addTags: $addTags
      }
    ) {
      runsSQL {
        id
        name
        __typename
        ...SelectRunFragment
        ...BasicRunFragment
        user {
          username
          photoUrl
        }
      }
    }
  }
  ${fragments.selectRun}
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

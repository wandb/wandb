import gql from 'graphql-tag';
import {fragments as runs} from './runs';

export const fragments = {
  detailedSweep: gql`
    fragment DetailedSweepFragment on SweepType {
      id
      name
      createdAt
      updatedAt
      description
      state
      config
      runCount
      runTime
      bestLoss
      agents {
        edges {
          node {
            id
            host
            fakeMetrics
            state
            createdAt
            heartbeatAt
          }
        }
      }
      runs {
        edges {
          node {
            id
            name
            createdAt
            history
          }
        }
      }
      user {
        username
        photoUrl
      }
    }
  `,
};

export const SWEEP_QUERY = gql`
query Model(
  $name: String!
  $entityName: String
  $sweepName: String!
) {
  model(name: $name, entityName: $entityName) {
    id
    name
    entityName
    description
    createdAt
    bucketCount
    access
    summaryMetrics
    sweep(name: $sweepName) {
      ...DetailedSweepFragment
    }
  }
}
${fragments.detailedSweep}
`;

export const SWEEP_UPSERT = gql`
  mutation upsertSweep($id: String, $description: String) {
    upsertSweep(input: {id: $id, description: $description}) {
      sweep {
        id
        name
        description
      }
      inserted
    }
  }
`;

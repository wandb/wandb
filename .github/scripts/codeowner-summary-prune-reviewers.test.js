const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const pruneReviewers = require('./codeowner-summary-prune-reviewers');
const {currentTeamSlugs, requestedCodeOwnerTeams, staleCodeOwnerTeams} =
  pruneReviewers;

test('currentTeamSlugs returns W&B team slugs', () => {
  const teams = currentTeamSlugs(`
wandb/sdk/foo.py @wandb/sdk-team @person
wandb/sdk/artifacts/bar.py @wandb/art-reg-team
  `);

  assert.deepEqual([...teams], ['sdk-team', 'art-reg-team']);
});

test('staleCodeOwnerTeams preserves current owners', () => {
  const staleTeams = staleCodeOwnerTeams(
    new Set(['sdk-team', 'art-reg-team']),
    ['sdk-team', 'launch-reviewers', 'sweeps-launch-team']
  );

  assert.deepEqual(staleTeams, ['launch-reviewers', 'sweeps-launch-team']);
});

test('requestedCodeOwnerTeams returns only team CODEOWNER requests', async () => {
  const responses = [
    {
      repository: {
        pullRequest: {
          reviewRequests: {
            nodes: [
              {
                asCodeOwner: true,
                requestedReviewer: {
                  __typename: 'Team',
                  slug: 'sdk-team',
                },
              },
              {
                asCodeOwner: false,
                requestedReviewer: {
                  __typename: 'Team',
                  slug: 'manually-requested-team',
                },
              },
              {
                asCodeOwner: true,
                requestedReviewer: {
                  __typename: 'User',
                },
              },
            ],
            pageInfo: {hasNextPage: true, endCursor: 'next'},
          },
        },
      },
    },
    {
      repository: {
        pullRequest: {
          reviewRequests: {
            nodes: [
              {
                asCodeOwner: true,
                requestedReviewer: {
                  __typename: 'Team',
                  slug: 'launch-reviewers',
                },
              },
            ],
            pageInfo: {hasNextPage: false, endCursor: null},
          },
        },
      },
    },
  ];
  const cursors = [];
  const github = {
    graphql: async (_query, variables) => {
      cursors.push(variables.cursor);
      return responses.shift();
    },
  };

  const teams = await requestedCodeOwnerTeams({
    github,
    owner: 'wandb',
    repo: 'wandb',
    pullNumber: 12934,
  });

  assert.deepEqual(teams, ['sdk-team', 'launch-reviewers']);
  assert.deepEqual(cursors, [null, 'next']);
});

test('pruneReviewers sends an empty reviewers list with stale teams', async t => {
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), 'prune-reviewers-'));
  fs.writeFileSync(
    path.join(workDir, 'codeowners_required.txt'),
    'wandb/sdk/foo.py @wandb/sdk-team\n'
  );
  const originalCwd = process.cwd();
  process.chdir(workDir);
  t.after(() => {
    process.chdir(originalCwd);
    fs.rmSync(workDir, {recursive: true, force: true});
  });

  const calls = [];
  const github = {
    graphql: async () => ({
      repository: {
        pullRequest: {
          reviewRequests: {
            nodes: [
              {
                asCodeOwner: true,
                requestedReviewer: {__typename: 'Team', slug: 'sdk-team'},
              },
              {
                asCodeOwner: true,
                requestedReviewer: {
                  __typename: 'Team',
                  slug: 'launch-reviewers',
                },
              },
            ],
            pageInfo: {hasNextPage: false, endCursor: null},
          },
        },
      },
    }),
    rest: {
      pulls: {
        removeRequestedReviewers: async params => calls.push(params),
      },
    },
  };

  await pruneReviewers({
    github,
    context: {
      repo: {owner: 'wandb', repo: 'wandb'},
      payload: {pull_request: {number: 12934}},
      issue: {number: 12934},
    },
    core: {notice: () => {}},
  });

  // The REST endpoint returns 422 when `reviewers` is absent, even for a
  // team-only removal.
  assert.deepEqual(calls, [
    {
      owner: 'wandb',
      repo: 'wandb',
      pull_number: 12934,
      reviewers: [],
      team_reviewers: ['launch-reviewers'],
    },
  ]);
});

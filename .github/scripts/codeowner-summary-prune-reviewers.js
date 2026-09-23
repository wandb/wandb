// Called by .github/workflows/codeowner-summary.yml via actions/github-script.
// Removes CODEOWNER team review requests that no longer match the PR's current
// diff.

const fs = require('fs');

function currentTeamSlugs(content) {
  const teams = new Set();
  for (const match of content.matchAll(/@wandb\/([\w.-]+)/g)) {
    teams.add(match[1]);
  }
  return teams;
}

async function requestedCodeOwnerTeams({github, owner, repo, pullNumber}) {
  const teams = [];
  let cursor = null;

  do {
    const result = await github.graphql(
      `
        query($owner: String!, $repo: String!, $pullNumber: Int!, $cursor: String) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pullNumber) {
              reviewRequests(first: 100, after: $cursor) {
                nodes {
                  asCodeOwner
                  requestedReviewer {
                    __typename
                    ... on Team { slug }
                  }
                }
                pageInfo {
                  hasNextPage
                  endCursor
                }
              }
            }
          }
        }
      `,
      {owner, repo, pullNumber, cursor}
    );

    const reviewRequests = result.repository.pullRequest.reviewRequests;
    for (const request of reviewRequests.nodes) {
      const reviewer = request.requestedReviewer;
      if (request.asCodeOwner && reviewer?.__typename === 'Team') {
        teams.push(reviewer.slug);
      }
    }

    cursor = reviewRequests.pageInfo.hasNextPage
      ? reviewRequests.pageInfo.endCursor
      : null;
  } while (cursor);

  return teams;
}

function staleCodeOwnerTeams(currentTeams, requestedTeams) {
  return requestedTeams.filter(team => !currentTeams.has(team));
}

async function pruneReviewers({github, context, core}) {
  const {owner, repo} = context.repo;
  const pullNumber =
    context.payload.pull_request?.number || context.issue.number;
  const currentTeams = currentTeamSlugs(
    fs.readFileSync('codeowners_required.txt', 'utf8')
  );
  const requestedTeams = await requestedCodeOwnerTeams({
    github,
    owner,
    repo,
    pullNumber,
  });
  const staleTeams = staleCodeOwnerTeams(currentTeams, requestedTeams);

  if (staleTeams.length === 0) {
    core.notice('No stale CODEOWNER team review requests found.');
    return;
  }

  // GitHub stores one review request per team. If someone manually requests a
  // team that GitHub previously requested as a code owner, the API does not
  // distinguish the manual intent from the CODEOWNER request. Such a team is
  // removed here when it no longer owns any file in the current diff.
  // The endpoint rejects a body without `reviewers` (422 Invalid request,
  // `"reviewers" wasn't supplied.`), even when only teams are being removed.
  await github.rest.pulls.removeRequestedReviewers({
    owner,
    repo,
    pull_number: pullNumber,
    reviewers: [],
    team_reviewers: staleTeams,
  });

  core.notice(
    `Removed stale CODEOWNER review requests: ${staleTeams.join(', ')}`
  );
}

module.exports = pruneReviewers;
module.exports.currentTeamSlugs = currentTeamSlugs;
module.exports.requestedCodeOwnerTeams = requestedCodeOwnerTeams;
module.exports.staleCodeOwnerTeams = staleCodeOwnerTeams;

// Called by .github/workflows/codeowner-summary.yml via actions/github-script.
// Groups changed files by their CODEOWNERS entries and writes the variables
// used to render the summary comment.
module.exports = async ({github, context, core}) => {
  const fs = require('fs');

  const content = fs.readFileSync('codeowners_required.txt', 'utf8');
  const fileOwnerMap = new Map();
  for (const line of content.trim().split('\n')) {
    if (!line.trim()) continue;
    const parts = line.trim().split(/\s+/);
    const filename = parts[0];
    const owners = parts.slice(1).filter(owner => owner !== '(unowned)');
    fileOwnerMap.set(
      filename,
      owners.length > 0 ? owners : ['No specific owner']
    );
  }

  const approvalMarkers = {
    approved: '✅',
    pending: '🟠',
  };

  async function getApprovedReviewers() {
    const pullNumber =
      context.payload.pull_request?.number || context.issue.number;
    const reviews = await github.paginate(github.rest.pulls.listReviews, {
      owner: context.repo.owner,
      repo: context.repo.repo,
      pull_number: pullNumber,
      per_page: 100,
    });

    const approvalStateByReviewer = new Map();
    for (const review of reviews
      .filter(review => review.user?.login && review.submitted_at)
      .sort((a, b) => new Date(a.submitted_at) - new Date(b.submitted_at))) {
      const login = review.user.login.toLowerCase();
      if (review.state === 'APPROVED') {
        approvalStateByReviewer.set(login, true);
      } else if (
        review.state === 'CHANGES_REQUESTED' ||
        review.state === 'DISMISSED'
      ) {
        approvalStateByReviewer.set(login, false);
      }
    }

    return new Set(
      Array.from(approvalStateByReviewer.entries())
        .filter(([, isApproved]) => isApproved)
        .map(([login]) => login)
    );
  }

  const approvedReviewers = await getApprovedReviewers();
  const teamApprovalCache = new Map();

  async function isApprovedOwner(owner) {
    const normalizedOwner = owner.toLowerCase();
    const teamMatch = normalizedOwner.match(/^@([^/]+)\/(.+)$/);

    if (!teamMatch) {
      return approvedReviewers.has(normalizedOwner.replace(/^@/, ''));
    }

    const [, org, teamSlug] = teamMatch;
    for (const reviewer of approvedReviewers) {
      const cacheKey = `${org}/${teamSlug}/${reviewer}`;
      if (!teamApprovalCache.has(cacheKey)) {
        teamApprovalCache.set(
          cacheKey,
          github.rest.teams
            .getMembershipForUserInOrg({
              org,
              team_slug: teamSlug,
              username: reviewer,
            })
            .then(({data}) => data.state === 'active')
            .catch(error => {
              if (error.status !== 404) {
                core.warning(
                  `Could not check whether @${reviewer} belongs to ` +
                    `@${org}/${teamSlug}: ${error.message}`
                );
              }
              return false;
            })
        );
      }

      if (await teamApprovalCache.get(cacheKey)) {
        return true;
      }
    }

    return false;
  }

  async function approvalStatusForOwners(owners) {
    for (const owner of owners) {
      if (await isApprovedOwner(owner)) {
        return 'approved';
      }
    }
    return 'pending';
  }

  const ownerSetToFiles = new Map();
  for (const [file, owners] of fileOwnerMap) {
    const ownerKey = [...owners].sort().join(', ');
    if (!ownerSetToFiles.has(ownerKey)) {
      ownerSetToFiles.set(ownerKey, []);
    }
    ownerSetToFiles.get(ownerKey).push(file);
  }

  const sortedOwnerSets = Array.from(ownerSetToFiles.entries()).sort(
    (a, b) => b[1].length - a[1].length
  );

  const ownerGroups = await Promise.all(
    sortedOwnerSets.map(async ([ownerSet, files]) => {
      const owners = ownerSet.split(', ');
      const approvalStatus = owners.includes('No specific owner')
        ? null
        : await approvalStatusForOwners(owners);

      return {
        owners: ownerSet,
        approval_marker: approvalStatus ? approvalMarkers[approvalStatus] : '',
        files: files.sort().map(path => ({path})),
      };
    })
  );

  const vars = {
    file_count: fileOwnerMap.size,
    owner_groups: ownerGroups,
    github_run_id: context.runId,
    // eslint-disable-next-line node/no-process-env
    github_run_url: `${context.serverUrl}/${process.env.GITHUB_REPOSITORY}/actions/runs/${context.runId}`,
  };

  fs.writeFileSync('template-vars.json', JSON.stringify(vars, null, 2));
};

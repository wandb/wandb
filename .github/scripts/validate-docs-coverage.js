const core = require('@actions/core');
const github = require('@actions/github');

// Extracting the PR information from the context
const pr = github.context.payload.pull_request;
const prTitle = pr.title || '';
const prBody = pr.body || '';

// Function to create failure comment
async function createFailureComment(message) {
  // Use the environment variable GITHUB_TOKEN directly for authentication
  const octokit = github.getOctokit(process.env.GITHUB_TOKEN); // Passing the token here
  await octokit.rest.issues.createComment({
    owner: github.context.repo.owner,
    repo: github.context.repo.repo,
    issue_number: pr.number,
    body: `❌ Documentation Reference Check Failed\n\n${message}\n\nThis check is required for all PRs that start with "feat". Please update your PR description and this check will run again automatically.`
  });
  core.setFailed(message);
}

// Main async function that handles all the logic
async function main() {
  // Use the environment variable GITHUB_TOKEN directly for authentication
  const octokit = github.getOctokit(process.env.GITHUB_TOKEN); // Passing the token here

  // First, cleanup any previous comments from this workflow
  const comments = await octokit.rest.issues.listComments({
    owner: github.context.repo.owner,
    repo: github.context.repo.repo,
    issue_number: pr.number
  });

  // Delete any previous failure comments from this workflow
  for (const comment of comments.data) {
    if (comment.body.startsWith('❌ Documentation Reference Check Failed')) {
      await octokit.rest.issues.deleteComment({
        owner: github.context.repo.owner,
        repo: github.context.repo.repo,
        comment_id: comment.id
      });
    }
  }

  // Check if PR title starts with "feat"
  if (!prTitle.startsWith('feat')) {
    console.log('PR title does not start with "feat". Skipping documentation check.');
    return;
  }

  // Regular expressions to match either:
  const docsLinkRegex = /(?:https:\/\/github\.com\/wandb\/docs\/pull\/|wandb\/docs#)(\d+)/;
  const jiraLinkRegex = /(?:https:\/\/wandb\.atlassian\.net\/browse\/)?DOCS-\d+/;

  const docsPrMatch = prBody.match(docsLinkRegex);
  const jiraMatch = prBody.match(jiraLinkRegex);

  if (!docsPrMatch && !jiraMatch) {
    await createFailureComment(
      'No documentation reference found in the PR description. Please add either:\n' +
      '- A link to a docs PR (format: wandb/docs#XXX or https://github.com/wandb/docs/pull/XXX)\n' +
      '- A Jira ticket reference (format: DOCS-XXX or https://wandb.atlassian.net/browse/DOCS-XXX)'
    );
    return;
  }

  // If we found a docs PR link, validate that it exists and is open
  if (docsPrMatch) {
    const docsPrNumber = docsPrMatch[1];

    try {
      const docsPr = await octokit.rest.pulls.get({
        owner: 'wandb',
        repo: 'docs',
        pull_number: parseInt(docsPrNumber)
      });

      if (docsPr.data.state !== 'open') {
        await createFailureComment(
          `The linked documentation PR #${docsPrNumber} is not open. Please ensure the documentation PR is open before merging this PR.`
        );
        return;
      }

      console.log(`✅ Found corresponding docs PR: #${docsPrNumber}`);
    } catch (error) {
      if (error.status === 404) {
        await createFailureComment(
          `Documentation PR #${docsPrNumber} not found. Please ensure the PR number is correct.`
        );
      } else {
        await createFailureComment(
          `Error checking docs PR: ${error.message}`
        );
      }
      return;
    }
  }

  // If we found a Jira ticket link, we don't need to validate it further
  if (jiraMatch) {
    console.log(`✅ Found corresponding DOCS Jira ticket: ${jiraMatch[0]}`);
  }
}

// Call the main async function
main().catch(error => console.error(error));

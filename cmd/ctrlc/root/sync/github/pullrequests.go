package github

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/kinds"
	"github.com/google/go-github/v57/github"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
	"golang.org/x/oauth2"
)

// NewSyncPullRequestCmd creates a new cobra command for syncing GitHub pull requests
func NewSyncPullRequestsCmd() *cobra.Command {
	var repoPath string
	var token string
	var name string
	var states []string

	cmd := &cobra.Command{
		Use:   "pull-requests",
		Short: "Sync GitHub pull requests into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure GitHub credentials are configured via environment variables or token

			# Sync all pull requests from a repository
			$ ctrlc sync github pull-requests --owner myorg --repo myrepo --token ghp_yourtokenhere

			# Sync only open pull requests
			$ ctrlc sync github pull-requests --owner myorg --repo myrepo --state open

			# Sync only draft pull requests
			$ ctrlc sync github pull-requests --owner myorg --repo myrepo --state draft

			# Sync only merged pull requests
			$ ctrlc sync github pull-requests --owner myorg --repo myrepo --state merged

			# Sync only closed but not merged pull requests
			$ ctrlc sync github pull-requests --owner myorg --repo myrepo --state closed

			# Sync multiple states
			$ ctrlc sync github pull-requests --owner myorg --repo myrepo --state open --state draft
		`),
		PreRunE: validateFlags(&repoPath, &states),
		RunE:    runSync(&repoPath, &token, &name, &states),
	}

	// Add command flags
	cmd.Flags().StringVarP(&name, "provider", "p", "", "Name of the resource provider")
	cmd.Flags().StringVarP(&repoPath, "repo", "r", "", "GitHub repository name (owner/repo)")
	cmd.Flags().StringVarP(&token, "token", "t", "", "GitHub API token (can also be set via GITHUB_TOKEN env var)")
	cmd.Flags().StringSliceVarP(&states, "state", "s", []string{"open"}, "Filter pull requests by state: all, open, closed, draft, merged (can be specified multiple times)")
	cmd.MarkFlagRequired("repo")

	return cmd
}

// validateFlags ensures required flags are set and validates flag combinations
func validateFlags(repoPath *string, states *[]string) func(cmd *cobra.Command, args []string) error {
	return func(cmd *cobra.Command, args []string) error {
		// Extract owner from repo string if it's in the format "owner/repo"
		var owner string
		var repo string
		parts := strings.Split(*repoPath, "/")
		if len(parts) == 2 {
			owner = parts[0]
			repo = parts[1]
			log.Debug("Extracted owner and repo from repo string", "owner", owner, "repo", repo)
		}

		log.Debug("Validating flags", "owner", owner, "repo", repo, "states", *states)

		if owner == "" {
			return fmt.Errorf("owner is required (use --owner flag or specify repo as 'owner/repo')")
		}
		if repo == "" {
			return fmt.Errorf("repo is required")
		}

		// Validate state values
		validStates := map[string]bool{
			"all":    true,
			"open":   true,
			"closed": true,
			"draft":  true,
			"merged": true,
		}

		for _, state := range *states {
			if !validStates[state] {
				log.Debug("Invalid state value", "state", state)
				return fmt.Errorf("invalid state value: %s, must be one of: all, open, closed, draft, merged", state)
			}
		}

		// If "all" is specified with other states, return an error
		if len(*states) > 1 {
			for _, state := range *states {
				if state == "all" {
					log.Debug("Cannot specify 'all' with other states")
					return fmt.Errorf("cannot specify 'all' with other states")
				}
			}
		}

		log.Debug("Flag validation successful")
		return nil
	}
}

// runSync contains the main sync logic
func runSync(repoPath, token, name *string, states *[]string) func(cmd *cobra.Command, args []string) error {
	return func(cmd *cobra.Command, args []string) error {
		log.Info("Syncing GitHub pull requests into Ctrlplane",
			"repoPath", *repoPath,
			"states", *states)

		ctx := context.Background()

		// Get token from flag or environment
		githubToken := *token
		if githubToken == "" {
			log.Debug("Token not provided via flag, checking environment")
			githubToken = os.Getenv("GITHUB_TOKEN")
			if githubToken == "" {
				log.Debug("GitHub token not found in environment")
				return fmt.Errorf("GitHub token is required (use --token flag or set GITHUB_TOKEN env var)")
			}
			log.Debug("Found GitHub token in environment")
		}

		// Initialize GitHub client
		log.Debug("Initializing GitHub client")
		client, err := initGitHubClient(ctx, githubToken)
		if err != nil {
			log.Error("Failed to initialize GitHub client", "error", err)
			return err
		}
		log.Debug("GitHub client initialized successfully")

		// List and process pull requests
		log.Debug("Processing pull requests", "repoPath", *repoPath)

		pathSplit := strings.Split(*repoPath, "/")
		owner := pathSplit[0]
		repo := pathSplit[1]

		resources, err := processPullRequests(ctx, client, owner, repo, *states)
		if err != nil {
			log.Error("Failed to process pull requests", "error", err)
			return err
		}
		log.Debug("Pull requests processed successfully", "count", len(resources))

		// Upsert resources to Ctrlplane
		log.Debug("Upserting resources to Ctrlplane", "count", len(resources))
		return upsertToCtrlplane(ctx, resources, owner, repo, *name)
	}
}

// initGitHubClient creates a new GitHub client
func initGitHubClient(ctx context.Context, token string) (*github.Client, error) {
	log.Debug("Creating GitHub client with token")
	ts := oauth2.StaticTokenSource(
		&oauth2.Token{AccessToken: token},
	)
	tc := oauth2.NewClient(ctx, ts)
	client := github.NewClient(tc)
	log.Debug("GitHub client created successfully")
	return client, nil
}

// processPullRequests lists and processes all pull requests
func processPullRequests(ctx context.Context, client *github.Client, owner, repo string, states []string) ([]api.AgentResource, error) {
	log.Debug("Processing pull requests", "owner", owner, "repo", repo, "states", states)

	// If no states specified or "all" is specified, include everything
	fetchAll := len(states) == 0
	log.Debug("Fetch all states", "fetchAll", fetchAll)

	// Determine which API calls to make
	fetchOpen := true
	fetchClosed := true

	if !fetchAll {
		fetchOpen = false
		fetchClosed = false
		statesToFetch := map[string]bool{}
		for _, state := range states {
			statesToFetch[state] = true
		}

		// Need to fetch open PRs if any of the requested states are open or draft
		if statesToFetch["open"] || statesToFetch["draft"] {
			fetchOpen = true
		}

		// Need to fetch closed PRs if any of the requested states are closed or merged
		if statesToFetch["closed"] || statesToFetch["merged"] {
			fetchClosed = true
		}
	}

	log.Debug("API calls to make", "fetchOpen", fetchOpen, "fetchClosed", fetchClosed)

	var allPRs []*github.PullRequest

	// Fetch open PRs if needed
	if fetchOpen {
		log.Debug("Fetching open PRs")
		prs, err := fetchPRs(ctx, client, owner, repo, "open")
		if err != nil {
			log.Error("Failed to fetch open PRs", "error", err)
			return nil, err
		}
		log.Debug("Fetched open PRs", "count", len(prs))
		allPRs = append(allPRs, prs...)
	}

	// Fetch closed PRs if needed
	if fetchClosed {
		log.Debug("Fetching closed PRs")
		prs, err := fetchPRs(ctx, client, owner, repo, "closed")
		if err != nil {
			log.Error("Failed to fetch closed PRs", "error", err)
			return nil, err
		}
		log.Debug("Fetched closed PRs", "count", len(prs))
		allPRs = append(allPRs, prs...)
	}

	// Apply filters based on the requested states
	var filteredPRs []*github.PullRequest

	if fetchAll {
		// Include all PRs without filtering
		log.Debug("Including all PRs without filtering")
		filteredPRs = allPRs
	} else {
		log.Debug("Filtering PRs by requested states", "states", states)
		stateFilters := map[string]bool{}
		for _, state := range states {
			stateFilters[state] = true
		}

		for _, pr := range allPRs {
			// Normalize the PR status
			status := getNormalizedStatus(pr)
			log.Debug("Checking PR status", "number", pr.GetNumber(), "status", status)

			if stateFilters[status] {
				log.Debug("Including PR in filtered results", "number", pr.GetNumber(), "status", status)
				filteredPRs = append(filteredPRs, pr)
			} else {
				log.Debug("Excluding PR from filtered results", "number", pr.GetNumber(), "status", status)
			}
		}
	}

	log.Info("Found GitHub pull requests",
		"total", len(allPRs),
		"filtered", len(filteredPRs),
		"states", states)

	resources := []api.AgentResource{}
	for _, pr := range filteredPRs {
		log.Info("Processing pull request", "number", pr.GetNumber(), "source", pr.GetHead().GetRef(), "target", pr.GetBase().GetRef())
		resource, err := processPullRequest(ctx, client, owner, repo, pr)
		if err != nil {
			log.Error("Failed to process pull request", "number", pr.GetNumber(), "error", err)
			continue
		}
		log.Debug("Successfully processed pull request", "number", pr.GetNumber())
		resources = append(resources, resource)
	}

	log.Debug("Finished processing all pull requests", "count", len(resources))
	return resources, nil
}

// fetchPRs fetches pull requests with the given state from GitHub
func fetchPRs(ctx context.Context, client *github.Client, owner, repo, state string) ([]*github.PullRequest, error) {
	log.Debug("Fetching pull requests", "owner", owner, "repo", repo, "state", state)
	opts := &github.PullRequestListOptions{
		State: state,
		ListOptions: github.ListOptions{
			PerPage: 100,
		},
	}

	var prs []*github.PullRequest
	page := 1
	for {
		log.Debug("Fetching page of pull requests", "page", page, "state", state)
		batch, resp, err := client.PullRequests.List(ctx, owner, repo, opts)
		if err != nil {
			log.Error("Failed to list pull requests", "state", state, "page", page, "error", err)
			return nil, fmt.Errorf("failed to list %s pull requests: %w", state, err)
		}
		log.Debug("Fetched pull requests", "state", state, "page", page, "count", len(batch))
		prs = append(prs, batch...)
		if resp.NextPage == 0 {
			log.Debug("No more pages to fetch", "state", state)
			break
		}
		opts.Page = resp.NextPage
		page = resp.NextPage
	}

	log.Debug("Completed fetching pull requests", "state", state, "total", len(prs))
	return prs, nil
}

// fetchAllCommits fetches all commits for a pull request with pagination support
func fetchAllCommits(ctx context.Context, client *github.Client, owner, repo string, prNumber int) ([]*github.RepositoryCommit, error) {
	var allCommits []*github.RepositoryCommit
	page := 1

	for {
		log.Debug("Fetching PR commits", "pr", prNumber, "page", page)

		commits, resp, err := client.PullRequests.ListCommits(ctx, owner, repo, prNumber, &github.ListOptions{
			Page:    page,
			PerPage: 100,
		})

		if err != nil {
			log.Error("Failed to list commits", "pr", prNumber, "page", page, "error", err)
			return nil, fmt.Errorf("failed to list commits for PR #%d (page %d): %w", prNumber, page, err)
		}

		log.Debug("Fetched commits", "pr", prNumber, "page", page, "count", len(commits))
		allCommits = append(allCommits, commits...)

		if resp.NextPage == 0 {
			log.Debug("No more commit pages to fetch", "pr", prNumber)
			break
		}

		page = resp.NextPage
	}

	log.Debug("Retrieved all commits for PR", "pr", prNumber, "count", len(allCommits))
	return allCommits, nil
}

// getBranchCommitInfo fetches the commits for a PR and returns info about oldest and newest
func getBranchCommitInfo(ctx context.Context, client *github.Client, owner, repo string, prNumber int) (map[string]any, map[string]any, int, error) {
	log.Debug("Getting branch commit info", "pr", prNumber)

	// Get all PR commits with pagination support
	commits, err := fetchAllCommits(ctx, client, owner, repo, prNumber)

	if err != nil {
		log.Error("Failed to fetch commits for PR", "pr", prNumber, "error", err)
		return nil, nil, 0, fmt.Errorf("failed to list PR commits: %w", err)
	}

	if len(commits) == 0 {
		log.Warn("No commits found for PR", "pr", prNumber)
		return nil, nil, 0, fmt.Errorf("no commits found for PR #%d", prNumber)
	}

	// First commit in the list should be the oldest one
	oldestCommit := commits[0]
	// Last commit in the list should be the newest one
	newestCommit := commits[len(commits)-1]

	// Add commit count to logs
	log.Debug("Processing PR commits", "pr", prNumber, "commit_count", len(commits))

	oldestCommitInfo := map[string]any{
		"sha":         oldestCommit.GetSHA(),
		"message":     strings.Split(oldestCommit.GetCommit().GetMessage(), "\n")[0], // Get first line
		"author":      oldestCommit.GetCommit().GetAuthor().GetName(),
		"authorEmail": oldestCommit.GetCommit().GetAuthor().GetEmail(),
		"url":         oldestCommit.GetHTMLURL(),
	}

	log.Debug("Oldest commit info", "pr", prNumber, "sha", oldestCommit.GetSHA())

	// Try to get commit date - using try/catch pattern with a function
	tryAddDate(oldestCommitInfo, "date", func() string {
		return oldestCommit.GetCommit().GetAuthor().GetDate().Format(time.RFC3339)
	})

	newestCommitInfo := map[string]any{
		"sha":         newestCommit.GetSHA(),
		"message":     strings.Split(newestCommit.GetCommit().GetMessage(), "\n")[0], // Get first line
		"author":      newestCommit.GetCommit().GetAuthor().GetName(),
		"authorEmail": newestCommit.GetCommit().GetAuthor().GetEmail(),
		"url":         newestCommit.GetHTMLURL(),
	}

	log.Debug("Newest commit info", "pr", prNumber, "sha", newestCommit.GetSHA())

	// Try to get commit date - using try/catch pattern with a function
	tryAddDate(newestCommitInfo, "date", func() string {
		return newestCommit.GetCommit().GetAuthor().GetDate().Format(time.RFC3339)
	})

	log.Debug("Successfully retrieved branch commit info", "pr", prNumber)
	return oldestCommitInfo, newestCommitInfo, len(commits), nil
}

// tryAddDate tries to add a date to a map with the given key and getter function
// This is a helper function to handle Timestamp objects without comparing to nil
func tryAddDate(m map[string]any, key string, getter func() string) {
	defer func() {
		// Recover from any panic that might occur in the getter
		if r := recover(); r != nil {
			log.Debug("Failed to get date", "key", key, "error", r)
			// Just ignore the error and don't add the date
		}
	}()

	// Try to get the date
	dateStr := getter()
	if dateStr != "" {
		m[key] = dateStr
		log.Debug("Added date to info", "key", key, "date", dateStr)
	} else {
		log.Debug("Date string was empty, not adding to info", "key", key)
	}
}

// getNormalizedStatus returns a normalized status for a pull request
func getNormalizedStatus(pr *github.PullRequest) string {
	status := "unknown"
	switch strings.ToLower(pr.GetState()) {
	case "open":
		if pr.GetDraft() {
			status = "draft"
		} else {
			status = "open"
		}
	case "closed":
		if pr.MergedAt != nil && !pr.MergedAt.IsZero() {
			status = "merged"
		} else {
			status = "closed"
		}
	}
	log.Debug("Normalized PR status", "number", pr.GetNumber(), "raw_state", pr.GetState(), "normalized", status)
	return status
}

// processPullRequest handles processing of a single pull request
func processPullRequest(ctx context.Context, client *github.Client, owner, repo string, pr *github.PullRequest) (api.AgentResource, error) {
	prNumber := pr.GetNumber()
	log.Debug("Processing pull request", "number", prNumber, "title", pr.GetTitle())

	metadata := initPullRequestMetadata(pr, owner, repo)
	log.Debug("Initialized PR metadata", "number", prNumber, "metadata_count", len(metadata))

	// Build console URL
	prUrl := pr.GetHTMLURL()
	metadata[kinds.CtrlplaneMetadataLinks] = fmt.Sprintf("{ \"GitHub Pull Request\": \"%s\" }", prUrl)
	log.Debug("Added PR URL to metadata", "number", prNumber, "url", prUrl)

	// Add branch information to the resource
	sourceBranch := pr.GetHead().GetRef()
	targetBranch := pr.GetBase().GetRef()
	log.Debug("PR branch info", "number", prNumber, "source", sourceBranch, "target", targetBranch)

	// Initialize the branch info map
	branchInfo := map[string]any{
		"source": sourceBranch,
		"target": targetBranch,
	}

	// Get commit information
	log.Debug("Getting branch commit info", "number", prNumber)
	oldestCommitInfo, newestCommitInfo, commitCount, err := getBranchCommitInfo(ctx, client, owner, repo, prNumber)
	if err == nil {
		if oldestCommitInfo != nil {
			branchInfo["oldestCommit"] = oldestCommitInfo
			log.Debug("Added oldest commit info", "number", prNumber)
		}
		if newestCommitInfo != nil {
			branchInfo["newestCommit"] = newestCommitInfo
			log.Debug("Added newest commit info", "number", prNumber)
		}
		metadata["git/commit-count"] = strconv.Itoa(commitCount)
		branchInfo["commitCount"] = commitCount
	} else {
		log.Warn("Failed to get branch commits", "pr", prNumber, "error", err)
	}

	resourceName := fmt.Sprintf("%s-%s-%d", owner, repo, prNumber)
	log.Debug("Creating resource", "number", prNumber, "name", resourceName)

	return api.AgentResource{
		Version:    "ctrlplane.dev/git/pull-request/v1",
		Kind:       "GitHubPullRequest",
		Name:       resourceName,
		Identifier: "github-" + pr.GetNodeID(),
		Config: map[string]any{
			"number":    prNumber,
			"url":       prUrl,
			"state":     pr.GetState(),
			"createdAt": pr.GetCreatedAt().Format(time.RFC3339),
			"updatedAt": pr.GetUpdatedAt().Format(time.RFC3339),
			"branch":    branchInfo,
			"isDraft":   pr.GetDraft(),
			"repository": map[string]any{
				"owner": owner,
				"name":  repo,
			},
			"author": map[string]any{
				"login":     pr.GetUser().GetLogin(),
				"avatarUrl": pr.GetUser().GetAvatarURL(),
			},
		},
		Metadata: metadata,
	}, nil
}

// initPullRequestMetadata initializes the base metadata for a pull request
func initPullRequestMetadata(pr *github.PullRequest, owner, repo string) map[string]string {
	prNumber := pr.GetNumber()
	log.Debug("Initializing PR metadata", "number", prNumber)

	normalizedStatus := getNormalizedStatus(pr)

	metadata := map[string]string{
		"ctrlplane/external-id": pr.GetNodeID(),

		"git/type":   "pull-request",
		"git/owner":  owner,
		"git/repo":   repo,
		"git/number": strconv.Itoa(prNumber),
		"git/title":  pr.GetTitle(),
		"git/state":  pr.GetState(),
		"git/status": normalizedStatus,
		"git/author": pr.GetUser().GetLogin(),
		"git/branch": pr.GetHead().GetRef(),

		"git/source-branch": pr.GetHead().GetRef(),
		"git/target-branch": pr.GetBase().GetRef(),
	}

	// Add draft status
	if pr.GetDraft() {
		metadata["git/draft"] = "true"
	} else {
		metadata["git/draft"] = "false"
	}

	// Process creation time
	if !pr.GetCreatedAt().IsZero() {
		createdAt := pr.GetCreatedAt().Format(time.RFC3339)
		metadata["git/created-at"] = createdAt
		log.Debug("PR creation time", "number", prNumber, "created_at", createdAt)
	}

	// Process update time
	if !pr.GetUpdatedAt().IsZero() {
		updatedAt := pr.GetUpdatedAt().Format(time.RFC3339)
		metadata["git/updated-at"] = updatedAt
		log.Debug("PR update time", "number", prNumber, "updated_at", updatedAt)
	}

	// Process merge time
	if pr.MergedAt != nil && !pr.MergedAt.IsZero() {
		mergedAt := pr.MergedAt.Format(time.RFC3339)
		metadata["git/merged-at"] = mergedAt
		log.Debug("PR merge time", "number", prNumber, "merged_at", mergedAt)

		if pr.MergedBy != nil {
			mergedBy := pr.MergedBy.GetLogin()
			metadata["git/merged-by"] = mergedBy
			log.Debug("PR merged by", "number", prNumber, "merged_by", mergedBy)
		}
	}

	// Process closed time
	if pr.ClosedAt != nil && !pr.ClosedAt.IsZero() {
		closedAt := pr.ClosedAt.Format(time.RFC3339)
		metadata["git/closed-at"] = closedAt
		log.Debug("PR close time", "number", prNumber, "closed_at", closedAt)
	}

	// Add additions and deletions counts
	metadata["git/additions"] = strconv.Itoa(pr.GetAdditions())
	metadata["git/deletions"] = strconv.Itoa(pr.GetDeletions())
	metadata["git/changed-files"] = strconv.Itoa(pr.GetChangedFiles())
	log.Debug("PR change stats", "number", prNumber, "additions", pr.GetAdditions(), "deletions", pr.GetDeletions(), "files", pr.GetChangedFiles())

	labels := make([]string, len(pr.Labels))
	for i, label := range pr.Labels {
		labels[i] = label.GetName()
	}
	metadata["git/labels"] = strings.Join(labels, ",")

	log.Debug("Completed PR metadata initialization", "number", prNumber, "metadata_count", len(metadata))
	return metadata
}

var relationshipRules = []api.CreateResourceRelationshipRule{}

// upsertToCtrlplane handles upserting resources to Ctrlplane
func upsertToCtrlplane(ctx context.Context, resources []api.AgentResource, owner, repo, name string) error {
	log.Debug("Upserting resources to Ctrlplane", "count", len(resources))

	if name == "" {
		name = fmt.Sprintf("github-prs-%s-%s", owner, repo)
		log.Debug("Using generated provider name", "name", name)
	} else {
		log.Debug("Using provided provider name", "name", name)
	}

	apiURL := viper.GetString("url")
	apiKey := viper.GetString("api-key")
	workspaceId := viper.GetString("workspace")

	log.Debug("API configuration", "url", apiURL, "workspace", workspaceId)

	log.Debug("Creating API client")
	ctrlplaneClient, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
	if err != nil {
		log.Error("Failed to create API client", "error", err)
		return fmt.Errorf("failed to create API client: %w", err)
	}

	log.Debug("Creating resource provider", "name", name)
	rp, err := api.NewResourceProvider(ctrlplaneClient, workspaceId, name)
	if err != nil {
		log.Error("Failed to create resource provider", "name", name, "error", err)
		return fmt.Errorf("failed to create resource provider: %w", err)
	}

	log.Debug("Adding resource relationship rules", "rules_count", len(relationshipRules))
	err = rp.AddResourceRelationshipRule(ctx, relationshipRules)
	if err != nil {
		log.Error("Failed to add resource relationship rule", "name", name, "error", err)
	} else {
		log.Debug("Successfully added relationship rules")
	}

	log.Debug("Upserting resources", "count", len(resources))
	upsertResp, err := rp.UpsertResource(ctx, resources)
	if err != nil {
		log.Error("Failed to upsert resources", "error", err)
		return fmt.Errorf("failed to upsert resources: %w", err)
	}

	log.Info("Response from upserting resources", "status", upsertResp.Status)
	log.Debug("Successfully upserted resources to Ctrlplane")
	return nil
}

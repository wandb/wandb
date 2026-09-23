package leet

import (
	"context"
	"fmt"
	"slices"
	"time"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
)

// remoteRunsPageSize is how many runs a discovery request lists.
const remoteRunsPageSize = 100

// RemoteWorkspaceBackend lists the runs of a W&B project and reads their
// history from the W&B backend.
//
// Discovery pages through the project once, newest runs first, and then
// re-lists the newest page every remotePollInterval to pick up new runs and
// state changes. Discovery commands run one at a time, each scheduled after
// the previous result is handled, so the listing state needs no lock.
type RemoteWorkspaceBackend struct {
	baseURL string
	entity  string
	project string
	clients *remoteClients
	logger  *observability.CoreLogger

	// runIDs are the listed runs, newest first.
	runIDs []string

	// cursor is where the rest of the initial listing starts.
	cursor *string

	// listed reports whether the initial listing is complete.
	listed bool

	// err is the error of the last discovery, if any.
	err error
}

// NewRemoteWorkspaceBackend creates a backend for a remote W&B project.
func NewRemoteWorkspaceBackend(
	baseURL string,
	entity string,
	project string,
	logger *observability.CoreLogger,
) (*RemoteWorkspaceBackend, error) {
	clients, err := newRemoteClients(baseURL, logger)
	if err != nil {
		return nil, err
	}
	return &RemoteWorkspaceBackend{
		baseURL: baseURL,
		entity:  entity,
		project: project,
		clients: clients,
		logger:  logger,
	}, nil
}

func (b *RemoteWorkspaceBackend) DiscoverRunsCmd(delay time.Duration) tea.Cmd {
	return tea.Tick(delay, func(time.Time) tea.Msg {
		runs, err := b.listRuns()
		b.err = err
		if err != nil {
			return WorkspaceRunDiscoveryMsg{Err: err}
		}
		return WorkspaceRunDiscoveryMsg{RunKeys: b.runIDs, Runs: runs}
	})
}

// listRuns fetches the next page of the initial listing, or the newest
// page once the listing is complete, and returns the runs on it.
func (b *RemoteWorkspaceBackend) listRuns() (map[string]RunMsg, error) {
	var cursor *string
	if !b.listed {
		cursor = b.cursor
	}
	first, order := remoteRunsPageSize, "-created_at"
	response, err := gql.QueryProjectRuns(
		context.Background(),
		b.clients.graphql,
		b.entity,
		b.project,
		&first,
		&order,
		cursor,
	)
	if err != nil {
		return nil, err
	}
	if response.Project == nil || response.Project.Runs == nil {
		return nil, fmt.Errorf("project %s/%s not found", b.entity, b.project)
	}

	page := response.Project.Runs
	runs := make(map[string]RunMsg, len(page.Edges))
	var newIDs []string
	for _, edge := range page.Edges {
		info := newRunInfo(b.entity, b.project, &edge.Node.LeetRun, b.logger)
		runs[info.runId] = info.runMsg()
		// Runs created while paging shift later pages, repeating runs.
		if !slices.Contains(b.runIDs, info.runId) {
			newIDs = append(newIDs, info.runId)
		}
	}

	if b.listed {
		b.runIDs = append(newIDs, b.runIDs...)
	} else {
		b.runIDs = append(b.runIDs, newIDs...)
		b.cursor = page.PageInfo.EndCursor
		b.listed = !page.PageInfo.HasNextPage
	}
	return runs, nil
}

func (b *RemoteWorkspaceBackend) NextDiscoveryCmd() tea.Cmd {
	if b.listed || b.err != nil {
		return b.DiscoverRunsCmd(remotePollInterval)
	}
	return b.DiscoverRunsCmd(0)
}

func (b *RemoteWorkspaceBackend) InitReaderCmd(runKey string) tea.Cmd {
	return func() tea.Msg {
		source, err := b.clients.openRun(
			context.Background(), b.entity, b.project, runKey, b.logger)
		if err != nil {
			return WorkspaceInitErrMsg{RunKey: runKey, Err: err}
		}
		return WorkspaceRunInitMsg{RunKey: runKey, Reader: source}
	}
}

// PreloadOverviewCmd implements WorkspaceBackend.
//
// Discovery lists remote runs with their metadata, so there is nothing
// to preload.
func (b *RemoteWorkspaceBackend) PreloadOverviewCmd(string) tea.Cmd {
	return nil
}

func (b *RemoteWorkspaceBackend) RunParams(runKey string) *RunParams {
	return &RunParams{
		Remote: &RemoteRunParams{
			BaseURL: b.baseURL,
			Entity:  b.entity,
			Project: b.project,
			RunID:   runKey,
		},
	}
}

func (b *RemoteWorkspaceBackend) SeriesKey(runKey string) string {
	return b.entity + "/" + b.project + "/" + runKey
}

func (b *RemoteWorkspaceBackend) DisplayLabel() string {
	return "project: " + b.entity + "/" + b.project
}

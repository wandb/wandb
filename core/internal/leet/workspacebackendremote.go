package leet

import (
	"context"
	"errors"
	"fmt"
	"os"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	defaultRemoteRunLimit = 100
)

var ErrRunNotFound = errors.New("run not found")

// RemoteWorkspaceBackend discovers runs via GraphQL and reads history
// from parquet files hosted on the W&B backend.
type RemoteWorkspaceBackend struct {
	baseURL string
	entity  string
	project string

	graphqlClient graphql.Client
	httpClient    api.RetryableClient

	// runInfos stores metadata fetched from the discovery query,
	// keyed by run ID (the GraphQL "name" field).
	runInfos map[string]*RunInfo

	logger *observability.CoreLogger

	hasMore bool
	cursor  *string
}

// NewRemoteWorkspaceBackend creates a backend for a remote W&B project.
// Clients are initialized lazily on the first DiscoverRunsCmd call.
func NewRemoteWorkspaceBackend(
	baseURL string,
	entity string,
	project string,
	logger *observability.CoreLogger,
) *RemoteWorkspaceBackend {
	apiKey := os.Getenv("WANDB_API_KEY")
	if apiKey == "" {
		return nil
	}

	settingsProto := &spb.Settings{
		ApiKey:  wrapperspb.String(apiKey),
		BaseUrl: wrapperspb.String(baseURL),
	}
	s := settings.From(settingsProto)

	graphqlClient := initGraphQLClient(s, logger)
	httpClient := api.NewClient(api.ClientOptions{
		BaseURL:            stream.BaseURLFromSettings(logger, s),
		RetryMax:           3,
		RetryWaitMin:       1 * time.Second,
		RetryWaitMax:       10 * time.Second,
		NonRetryTimeout:    10 * time.Second,
		CredentialProvider: stream.CredentialsFromSettings(logger, s),
		Logger:             logger.Logger,
	})

	return &RemoteWorkspaceBackend{
		baseURL:       baseURL,
		entity:        entity,
		project:       project,
		runInfos:      make(map[string]*RunInfo),
		logger:        logger,
		hasMore:       false,
		graphqlClient: graphqlClient,
		httpClient:    httpClient,
	}
}

func (b *RemoteWorkspaceBackend) DiscoverRunsCmd(delay time.Duration) tea.Cmd {
	if delay < 0 {
		delay = 0
	}

	entity := b.entity
	project := b.project
	logger := b.logger

	return tea.Tick(delay, func(time.Time) tea.Msg {
		first := defaultRemoteRunLimit
		order := "-created_at"
		response, err := gql.QueryProjectRuns(
			context.Background(),
			b.graphqlClient,
			entity,
			project,
			&first,
			&order,
			b.cursor,
		)
		if err != nil {
			return WorkspaceRunDiscoveryMsg{Err: err}
		}

		if response.Project == nil || response.Project.Runs == nil {
			return WorkspaceRunDiscoveryMsg{
				Err: fmt.Errorf("project %s/%s not found", entity, project),
			}
		}

		b.hasMore = response.Project.Runs.PageInfo.HasNextPage
		b.cursor = response.Project.Runs.PageInfo.EndCursor

		edges := response.Project.Runs.Edges
		for _, edge := range edges {
			node := edge.Node
			runKey := node.Name

			var displayName string
			if node.DisplayName != nil {
				displayName = *node.DisplayName
			}

			var runSummary map[string]any
			if node.SummaryMetrics != nil {
				parsed, parseErr := simplejsonext.UnmarshalObjectString(*node.SummaryMetrics)
				if parseErr != nil {
					logger.Warn("remote workspace: failed to parse summary metrics",
						"run", runKey, "error", parseErr)
				} else {
					runSummary = parsed
				}
			}

			b.runInfos[runKey] = NewRunInfo(
				entity,
				project,
				runKey,
				runSummary,
				displayName,
			)
		}

		runKeys := make([]string, 0, len(b.runInfos))
		for runKey := range b.runInfos {
			runKeys = append(runKeys, runKey)
		}

		return WorkspaceRunDiscoveryMsg{RunKeys: runKeys}
	})
}

func (b *RemoteWorkspaceBackend) NextDiscoveryCmd() tea.Cmd {
	// Remote workspaces only poll once during startup.
	if !b.hasMore {
		return nil
	}

	return b.DiscoverRunsCmd(0)
}

func (b *RemoteWorkspaceBackend) InitReaderCmd(runKey string) tea.Cmd {
	info := b.runInfos[runKey]
	logger := b.logger
	graphqlClient := b.graphqlClient
	httpClient := b.httpClient
	entity := b.entity
	project := b.project

	return func() tea.Msg {
		source, err := NewParquetHistorySource(
			entity,
			project,
			runKey,
			graphqlClient,
			httpClient,
			info,
			logger,
		)
		if err != nil {
			return WorkspaceInitErrMsg{
				RunKey: runKey,
				Err:    err,
			}
		}
		return WorkspaceRunInitMsg{
			RunKey: runKey,
			Reader: source,
		}
	}
}

func (b *RemoteWorkspaceBackend) PreloadOverviewCmd(runKey string) tea.Cmd {
	info := b.runInfos[runKey]
	return func() tea.Msg {
		if info == nil {
			return WorkspaceRunOverviewPreloadedMsg{
				RunKey: runKey,
				Err:    ErrRunNotFound,
			}
		}
		return WorkspaceRunOverviewPreloadedMsg{
			RunKey: runKey,
			Run: &RunMsg{
				ID:          info.runId,
				Project:     info.project,
				DisplayName: info.displayName,
			},
		}
	}
}

func (b *RemoteWorkspaceBackend) RunParams(runKey string) *RunParams {
	return &RunParams{
		RemoteRunParams: &RemoteRunParams{
			BaseURL: b.baseURL,
			Entity:  b.entity,
			Project: b.project,
			RunId:   runKey,
		},
	}
}

func (b *RemoteWorkspaceBackend) SeriesKey(runKey string) string {
	return runKey
}

func (b *RemoteWorkspaceBackend) DisplayLabel() string {
	return b.entity + "/" + b.project
}

func (b *RemoteWorkspaceBackend) SupportsLiveStreaming() bool {
	return false
}

package leet_test

import (
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func newTestRemoteBackend(
	mockGQL *gqlmock.MockClient,
) *leet.RemoteWorkspaceBackend {
	return leet.TestRemoteWorkspaceBackend(
		"https://api.wandb.ai",
		"test-entity",
		"test-project",
		mockGQL,
		nil, // httpClient not needed for discovery/preload tests
		observability.NewNoOpLogger(),
	)
}

const mockRunQueryResponse = `{
	"project": {
		"runs": {
			"edges": [
				{
					"node": {
						"name": "run-abc",
						"displayName": "First Run",
						"state": "finished",
						"createdAt": "2026-01-01T00:00:00Z",
						"summaryMetrics": "{\"loss\": 0.5}"
					}
				},
				{
					"node": {
						"name": "run-def",
						"displayName": "Second Run",
						"state": "running",
						"createdAt": "2026-01-02T00:00:00Z",
						"summaryMetrics": "{\"loss\": 0.3, \"acc\": 0.9}"
					}
				}
			],
			"pageInfo": {
				"endCursor": null,
				"hasNextPage": false
			}
		}
	}
}`

func TestRemoteWorkspaceBackend_DiscoverRunsCmd_Success(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	backend := newTestRemoteBackend(mockGQL)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryProjectRuns"),
		mockRunQueryResponse,
	)

	cmd := backend.DiscoverRunsCmd(0)
	require.NotNil(t, cmd)

	msg := cmd()
	discovery, ok := msg.(leet.WorkspaceRunDiscoveryMsg)
	require.True(t, ok, "expected WorkspaceRunDiscoveryMsg, got %T", msg)
	require.NoError(t, discovery.Err)
	assert.Len(t, discovery.RunKeys, 2)
	assert.Contains(t, discovery.RunKeys, "run-abc")
	assert.Contains(t, discovery.RunKeys, "run-def")
}

func TestRemoteWorkspaceBackend_DiscoverRunsCmd_Error(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	backend := newTestRemoteBackend(mockGQL)
	mockGQL.StubMatchWithError(
		gqlmock.WithOpName("QueryProjectRuns"),
		errors.New("network timeout"),
	)

	cmd := backend.DiscoverRunsCmd(0)
	msg := cmd()
	discovery, ok := msg.(leet.WorkspaceRunDiscoveryMsg)
	require.True(t, ok)
	require.Error(t, discovery.Err)
	assert.Contains(t, discovery.Err.Error(), "network timeout")
}

func TestRemoteWorkspaceBackend_DiscoverRunsCmd_ProjectNotFound(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	backend := newTestRemoteBackend(mockGQL)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryProjectRuns"),
		`{"project": null}`,
	)

	cmd := backend.DiscoverRunsCmd(0)
	msg := cmd()
	discovery, ok := msg.(leet.WorkspaceRunDiscoveryMsg)
	require.True(t, ok)
	require.Error(t, discovery.Err)
	assert.Contains(
		t,
		discovery.Err.Error(),
		"project test-entity/test-project not found",
	)
}

func TestRemoteWorkspaceBackend_NextDiscoveryCmd_NoMore(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	backend := newTestRemoteBackend(mockGQL)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryProjectRuns"),
		mockRunQueryResponse,
	)

	// Run initial discovery (initial response has hasNextPage=false).
	cmd := backend.DiscoverRunsCmd(0)
	cmd()

	// Next discovery response is nil because hasNextPage is false.
	assert.Nil(t, backend.NextDiscoveryCmd())
}

func TestRemoteWorkspaceBackend_NextDiscoveryCmd_HasMore(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	backend := newTestRemoteBackend(mockGQL)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryProjectRuns"),
		`{
			"project": {
				"runs": {
					"edges": [
						{
							"node": {
								"name": "run-page1",
								"displayName": "Page 1 Run",
								"state": "finished",
								"createdAt": "2026-01-01T00:00:00Z",
								"summaryMetrics": null
							}
						}
					],
					"pageInfo": {
						"endCursor": "cursor-abc",
						"hasNextPage": true
					}
				}
			}
		}`,
	)

	cmd := backend.DiscoverRunsCmd(0)
	cmd()

	// HasMore is true, so NextDiscoveryCmd should return a command.
	assert.NotNil(t, backend.NextDiscoveryCmd())
}

func TestRemoteWorkspaceBackend_PreloadOverviewCmd_ReturnsRunOverview(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	backend := newTestRemoteBackend(mockGQL)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryProjectRuns"),
		mockRunQueryResponse,
	)

	// Populate runInfos via discovery.
	cmd := backend.DiscoverRunsCmd(0)
	cmd()

	preloadCmd := backend.PreloadOverviewCmd("run-abc")
	require.NotNil(t, preloadCmd)

	msg := preloadCmd()

	preloaded, ok := msg.(leet.WorkspaceRunOverviewPreloadedMsg)
	require.True(t, ok, "expected WorkspaceRunOverviewPreloadedMsg, got %T", msg)
	require.NoError(t, preloaded.Err)
	assert.Equal(t, "run-abc", preloaded.RunKey)
	assert.Equal(t, "run-abc", preloaded.Run.ID)
	assert.Equal(t, "test-project", preloaded.Run.Project)
	assert.Equal(t, "First Run", preloaded.Run.DisplayName)
}

func TestRemoteWorkspaceBackend_PreloadOverviewCmd_UnknownRun(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	backend := newTestRemoteBackend(mockGQL)

	preloadCmd := backend.PreloadOverviewCmd("nonexistent-run")
	require.NotNil(t, preloadCmd)

	msg := preloadCmd()
	preloaded, ok := msg.(leet.WorkspaceRunOverviewPreloadedMsg)
	require.True(t, ok)
	assert.Equal(t, "nonexistent-run", preloaded.RunKey)
	assert.ErrorIs(t, preloaded.Err, leet.ErrRunNotFound)
}

func TestRemoteWorkspaceBackend_RunParams(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	backend := newTestRemoteBackend(mockGQL)

	params := backend.RunParams("run-xyz")

	require.NotNil(t, params)
	require.NotNil(t, params.RemoteRunParams)
	assert.Equal(t, "https://api.wandb.ai", params.BaseURL)
	assert.Equal(t, "test-entity", params.Entity)
	assert.Equal(t, "test-project", params.Project)
	assert.Equal(t, "run-xyz", params.RunId)
}

func TestRemoteWorkspaceBackend_DisplayLabel(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	backend := newTestRemoteBackend(mockGQL)

	assert.Equal(t, "test-entity/test-project", backend.DisplayLabel())
}

func TestRemoteWorkspaceBackend_SupportsLiveStreaming(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	backend := newTestRemoteBackend(mockGQL)

	assert.False(t, backend.SupportsLiveStreaming())
}

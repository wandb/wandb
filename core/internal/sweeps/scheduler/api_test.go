package scheduler_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func newTestAPI(
	client *gqlmock.MockClient,
	features map[spb.ServerFeature]bool,
) *scheduler.SweepAPI {
	return scheduler.NewSweepAPI(
		client,
		featurechecker.NewPreloaded(features),
		"test-entity",
		"test-project",
		"test-sweep",
	)
}

func supported() map[spb.ServerFeature]bool {
	return map[spb.ServerFeature]bool{
		spb.ServerFeature_SWEEPS_LOCAL_SCHEDULER: true,
	}
}

func TestCheckLocalSchedulerSupported(t *testing.T) {
	api := newTestAPI(gqlmock.NewMockClient(), supported())

	assert.NoError(t, api.CheckLocalSchedulerSupported(context.Background()))
}

func TestCheckLocalSchedulerUnsupported(t *testing.T) {
	api := newTestAPI(gqlmock.NewMockClient(), nil)

	err := api.CheckLocalSchedulerSupported(context.Background())

	assert.ErrorIs(t, err, scheduler.ErrUnsupportedServer)
}

func TestFetchSweep(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepConfig"),
		`{
			"project": {
				"sweep": {
					"id": "U3dlZXA6MQ==",
					"state": "RUNNING",
					"config": "method: grid",
					"displayName": "my-sweep",
					"controllerRunName": "controller-run-1"
				}
			}
		}`,
	)
	api := newTestAPI(client, supported())

	facts, err := api.FetchSweep(context.Background())

	require.NoError(t, err)
	assert.Equal(t, "U3dlZXA6MQ==", facts.NodeID)
	assert.Equal(t, "RUNNING", facts.State)
	assert.Equal(t, "method: grid", facts.Config)
	assert.Equal(t, "my-sweep", facts.DisplayName)
	assert.Equal(t, "controller-run-1", facts.ControllerRunName)
	assert.True(t, client.AllStubsUsed())
}

func TestFetchSweepNotFound(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepConfig"),
		`{"project": {"sweep": null}}`,
	)
	api := newTestAPI(client, supported())

	_, err := api.FetchSweep(context.Background())

	assert.ErrorIs(t, err, scheduler.ErrSweepNotFound)
}

func TestPollPage(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		`{
			"project": {
				"sweep": {
					"state": "RUNNING",
					"runs": {
						"pageInfo": {"hasNextPage": true, "endCursor": "abc"},
						"edges": [
							{
								"node": {
									"id": "UnVuOjE=",
									"name": "run-1",
									"state": "running",
									"config": "{\"param1\": {\"value\": 1}}",
									"summaryMetrics": "{\"loss\": 0.5}",
									"sampledHistory": [[{"loss": 1.0}, {"loss": 0.5}]]
								}
							}
						]
					}
				}
			}
		}`,
	)
	api := newTestAPI(client, supported())

	page, err := api.PollPage(context.Background(), 200, nil, "loss")

	require.NoError(t, err)
	assert.Equal(t, "RUNNING", page.SweepState)
	require.NotNil(t, page.NextCursor)
	assert.Equal(t, "abc", *page.NextCursor)
	require.Len(t, page.Runs, 1)
	run := page.Runs[0]
	assert.Equal(t, "UnVuOjE=", run.StorageID)
	assert.Equal(t, "run-1", run.Name)
	assert.Equal(t, "running", run.State)
	assert.Equal(t, `{"param1": {"value": 1}}`, run.ConfigJSON)
	assert.Equal(t, `{"loss": 0.5}`, run.SummaryJSON)
	assert.JSONEq(t, `[{"loss": 1.0}, {"loss": 0.5}]`, run.HistoryJSON)
}

func TestPollPageWithoutMetricSkipsHistory(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		`{
			"project": {
				"sweep": {
					"state": "RUNNING",
					"runs": {
						"pageInfo": {"hasNextPage": false, "endCursor": null},
						"edges": [
							{
								"node": {
									"id": "UnVuOjE=",
									"name": "run-1",
									"state": "finished",
									"config": "{}",
									"summaryMetrics": "{}",
									"sampledHistory": []
								}
							}
						]
					}
				}
			}
		}`,
	)
	api := newTestAPI(client, supported())

	page, err := api.PollPage(context.Background(), 200, nil, "")

	require.NoError(t, err)
	assert.Nil(t, page.NextCursor)
	require.Len(t, page.Runs, 1)
	assert.Equal(t, "", page.Runs[0].HistoryJSON)
}

func TestPollPageSweepNotFound(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		`{"project": null}`,
	)
	api := newTestAPI(client, supported())

	_, err := api.PollPage(context.Background(), 200, nil, "loss")

	assert.ErrorIs(t, err, scheduler.ErrSweepNotFound)
}

func TestConfirmRunExists(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("RunState"),
		`{"project": {"run": {"id": "UnVuOjE=", "state": "running"}}}`,
	)
	client.StubMatchOnce(
		gqlmock.WithOpName("RunState"),
		`{"project": {"run": null}}`,
	)
	api := newTestAPI(client, supported())

	exists, err := api.ConfirmRunExists(context.Background(), "run-1")
	require.NoError(t, err)
	assert.True(t, exists)

	exists, err = api.ConfirmRunExists(context.Background(), "run-gone")
	require.NoError(t, err)
	assert.False(t, exists)
}

func TestEnqueueRun(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("EnqueueSweepRun"),
		`{"enqueueSweepRun": {"id": "run-abc", "runQueueItemId": "rqi-1"}}`,
	)
	api := newTestAPI(client, supported())

	mintedID, err := api.EnqueueRun(
		context.Background(),
		"U3dlZXA6MQ==",
		`{"param1": {"value": 1}}`,
	)

	require.NoError(t, err)
	assert.Equal(t, "run-abc", mintedID)
	assert.True(t, client.AllStubsUsed())
}

func TestStopRun(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("StopRun"),
		`{"stopRun": {"success": true}}`,
	)
	api := newTestAPI(client, supported())

	stopped, err := api.StopRun(context.Background(), "UnVuOjE=")

	require.NoError(t, err)
	assert.True(t, stopped)
}

func TestUpsertSweepState(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("UpsertSweepState"),
		`{"upsertSweep": {"sweep": {"state": "FINISHED"}}}`,
	)
	api := newTestAPI(client, supported())

	err := api.UpsertSweepState(
		context.Background(), "U3dlZXA6MQ==", "FINISHED")

	require.NoError(t, err)
	assert.True(t, client.AllStubsUsed())
}

package scheduler_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func newTestAPI(
	client *gqlmock.MockClient,
	features map[spb.ServerFeature]bool,
) scheduler.SweepAPI {
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

// One warm-start page, read once and asserted from every angle: its
// rows, its cursor and the variables the request carried.
func TestWarmStartPage(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepPriorRuns"),
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
									"summaryMetrics": "{\"loss\": 0.5}"
								}
							}
						]
					}
				}
			}
		}`,
	)
	api := newTestAPI(client, supported())

	page, err := api.WarmStartPage(context.Background(), 200, nil)

	require.NoError(t, err)
	require.Len(t, page.Runs, 1)
	run := page.Runs[0]

	t.Run("the run's result reaches the caller", func(t *testing.T) {
		assert.Equal(t, "UnVuOjE=", run.StorageID)
		assert.Equal(t, "run-1", run.Name)
		assert.Equal(t, "running", run.State)
		assert.Equal(t, `{"param1": {"value": 1}}`, run.ConfigJSON)
		assert.Equal(t, `{"loss": 0.5}`, run.SummaryJSON)
	})

	t.Run("no history is requested or reported", func(t *testing.T) {
		// A prior run is replayed from its summary, and an empty spec
		// list would not spare the backend: it resolves sampledHistory
		// once per run regardless. So the field must not be selected.
		assert.Empty(t, run.HistoryJSON)
		request := client.AllRequests()[0]
		assert.NotContains(t, request.Query, "sampledHistory")
		assert.NotContains(t, requestVariables(t, request), "historySpecs")
	})

	t.Run("the sweep's state and cursor come back with the page", func(t *testing.T) {
		assert.Equal(t, "RUNNING", page.SweepState)
		require.NotNil(t, page.NextCursor)
		assert.Equal(t, "abc", *page.NextCursor)
	})
}

func TestWarmStartPageLastPageHasNoCursor(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepPriorRuns"),
		`{
			"project": {
				"sweep": {
					"state": "RUNNING",
					"runs": {
						"pageInfo": {"hasNextPage": false, "endCursor": "abc"},
						"edges": []
					}
				}
			}
		}`,
	)
	api := newTestAPI(client, supported())

	page, err := api.WarmStartPage(context.Background(), 200, nil)

	require.NoError(t, err)
	assert.Nil(t, page.NextCursor)
	assert.Empty(t, page.Runs)
}

func TestWarmStartPageSweepNotFound(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepPriorRuns"),
		`{"project": null}`,
	)
	api := newTestAPI(client, supported())

	_, err := api.WarmStartPage(context.Background(), 200, nil)

	assert.ErrorIs(t, err, scheduler.ErrSweepNotFound)
}

func TestFetchWatchedRuns(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepWatchedRuns"),
		`{
			"project": {
				"sweep": {"state": "RUNNING"},
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
								"sampledHistory": [[{"loss": 1.0, "_step": 0}]]
							}
						}
					]
				}
			}
		}`,
	)
	api := newTestAPI(client, supported())

	page, err := api.FetchWatchedRuns(
		context.Background(), []string{"run-1", "run-2"}, 200, nil, []string{"loss"})

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
	assert.JSONEq(t, `[{"loss": 1.0, "_step": 0}]`, run.HistoryJSON)

	// The whole point of the query: the backend is asked for exactly the
	// named runs rather than the whole sweep.
	gqlmock.AssertVariables(
		t,
		client.AllRequests()[0],
		gqlmock.GQLVar("filters", gomock.Eq(`{"name":{"$in":["run-1","run-2"]}}`)),
		gqlmock.GQLVar("historySpecs", historySpecsWantKeys("loss", "_step")),
	)
}

// The optimizer's early-terminate/prune policies plot each metric
// against _step, so the sampled-history spec must request _step
// alongside the metrics or the backend omits it from every row.
func TestFetchWatchedRunsSamplesEveryMetricAgainstStep(t *testing.T) {
	for name, testCase := range map[string]struct {
		metricKeys []string
		wantKeys   []string
	}{
		"one objective": {
			metricKeys: []string{"loss"},
			wantKeys:   []string{"loss", "_step"},
		},
		// Multi-objective sweeps compare runs against each other, so
		// every metric has to be sampled at the same steps.
		"several objectives": {
			metricKeys: []string{"loss", "accuracy"},
			wantKeys:   []string{"loss", "accuracy", "_step"},
		},
		"no objective": {
			metricKeys: nil,
			wantKeys:   []string{"_step"},
		},
	} {
		t.Run(name, func(t *testing.T) {
			client := gqlmock.NewMockClient()
			client.StubMatchOnce(
				gqlmock.WithOpName("SweepWatchedRuns"),
				`{
					"project": {
						"sweep": {"state": "RUNNING"},
						"runs": {
							"pageInfo": {"hasNextPage": false, "endCursor": null},
							"edges": []
						}
					}
				}`,
			)
			api := newTestAPI(client, supported())

			_, err := api.FetchWatchedRuns(
				context.Background(), []string{"run-1"}, 200, nil,
				testCase.metricKeys)

			require.NoError(t, err)
			gqlmock.AssertVariables(
				t,
				client.AllRequests()[0],
				gqlmock.GQLVar(
					"historySpecs",
					historySpecsWantKeys(testCase.wantKeys...),
				),
			)
		})
	}
}

func TestFetchWatchedRunsSweepNotFound(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepWatchedRuns"),
		`{"project": {"sweep": null, "runs": null}}`,
	)
	api := newTestAPI(client, supported())

	_, err := api.FetchWatchedRuns(
		context.Background(), []string{"run-1"}, 200, nil, nil)

	assert.ErrorIs(t, err, scheduler.ErrSweepNotFound)
}

// requestVariables decodes the variables a GraphQL request carried.
func requestVariables(t *testing.T, req *graphql.Request) map[string]any {
	t.Helper()

	encoded, err := json.Marshal(req.Variables)
	require.NoError(t, err)
	var vars map[string]any
	require.NoError(t, json.Unmarshal(encoded, &vars))
	return vars
}

// historySpecsWantKeys matches a historySpecs variable whose first spec
// requests exactly the given "keys", in order.
func historySpecsWantKeys(keys ...string) gomock.Matcher {
	return gomock.Cond(func(specs []any) bool {
		if len(specs) == 0 {
			return false
		}
		specJSON, ok := specs[0].(string)
		if !ok {
			return false
		}

		var spec struct {
			Keys []string `json:"keys"`
		}
		if err := json.Unmarshal([]byte(specJSON), &spec); err != nil {
			return false
		}

		return assert.ObjectsAreEqual(keys, spec.Keys)
	})
}

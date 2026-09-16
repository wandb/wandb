package scheduler_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/nullify"
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

// mustJSON marshals a gql response struct for use as a StubMatchOnce
// payload, so stubbed responses stay structurally valid against the
// generated GraphQL types instead of drifting hand-typed JSON strings.
func mustJSON(t *testing.T, v any) string {
	t.Helper()
	encoded, err := json.Marshal(v)
	require.NoError(t, err)
	return string(encoded)
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
		mustJSON(t, gql.SweepConfigResponse{
			Project: &gql.SweepConfigProject{
				Sweep: &gql.SweepConfigProjectSweep{
					Id:                "U3dlZXA6MQ==",
					State:             "RUNNING",
					Config:            "method: grid",
					DisplayName:       nullify.NilIfZero("my-sweep"),
					ControllerRunName: "controller-run-1",
				},
			},
		}),
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
		mustJSON(t, gql.SweepConfigResponse{
			Project: &gql.SweepConfigProject{Sweep: nil},
		}),
	)
	api := newTestAPI(client, supported())

	_, err := api.FetchSweep(context.Background())

	assert.ErrorIs(t, err, scheduler.ErrSweepNotFound)
}

func TestWarmStartPage(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		mustJSON(t, gql.SweepRunsWithHistoryResponse{
			Project: &gql.SweepRunsWithHistoryProject{
				Sweep: &gql.SweepRunsWithHistoryProjectSweep{
					State: "RUNNING",
					Runs: gql.SweepRunsWithHistoryProjectSweepRunsRunConnection{
						SweepPollRuns: gql.SweepPollRuns{
							PageInfo: gql.SweepPollRunsPageInfo{
								HasNextPage: true,
								EndCursor:   nullify.NilIfZero("abc"),
							},
							Edges: []gql.SweepPollRunsEdgesRunEdge{
								{
									Node: gql.SweepPollRunsEdgesRunEdgeNodeRun{
										Id:             "UnVuOjE=",
										Name:           "run-1",
										State:          nullify.NilIfZero("running"),
										Config:         nullify.NilIfZero(`{"param1": {"value": 1}}`),
										SummaryMetrics: nullify.NilIfZero(`{"loss": 0.5}`),
										SampledHistory: []interface{}{
											[]interface{}{
												map[string]interface{}{"loss": 1.0, "_step": 0},
												map[string]interface{}{"loss": 0.5, "_step": 1},
											},
										},
									},
								},
							},
						},
					},
				},
			},
		}),
	)
	api := newTestAPI(client, supported())

	page, err := api.WarmStartPage(context.Background(), 200, nil, []string{"loss"})

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
	assert.JSONEq(
		t,
		`[{"loss": 1.0, "_step": 0}, {"loss": 0.5, "_step": 1}]`,
		run.HistoryJSON,
	)

	// The optimizer's early-terminate/prune policies plot the metric
	// against _step, so the sampled-history spec must request both
	// keys or the backend silently omits _step from every row.
	gqlmock.AssertVariables(
		t,
		client.AllRequests()[0],
		gqlmock.GQLVar("historySpecs", historySpecsWantKeys("loss", "_step")),
	)
}

// TestWarmStartPageMultipleMetrics covers multi-objective sweeps, which
// track more than one metric and need every metric sampled at the same
// steps to compare runs against each other.
func TestWarmStartPageMultipleMetrics(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		mustJSON(t, gql.SweepRunsWithHistoryResponse{
			Project: &gql.SweepRunsWithHistoryProject{
				Sweep: &gql.SweepRunsWithHistoryProjectSweep{
					State: "RUNNING",
					Runs: gql.SweepRunsWithHistoryProjectSweepRunsRunConnection{
						SweepPollRuns: gql.SweepPollRuns{
							PageInfo: gql.SweepPollRunsPageInfo{
								HasNextPage: false,
								EndCursor:   nil,
							},
							Edges: []gql.SweepPollRunsEdgesRunEdge{
								{
									Node: gql.SweepPollRunsEdgesRunEdgeNodeRun{
										Id:             "UnVuOjE=",
										Name:           "run-1",
										State:          nullify.NilIfZero("running"),
										Config:         nullify.NilIfZero("{}"),
										SummaryMetrics: nullify.NilIfZero("{}"),
										SampledHistory: []interface{}{
											[]interface{}{
												map[string]interface{}{
													"loss":     1.0,
													"accuracy": 0.9,
													"_step":    0,
												},
											},
										},
									},
								},
							},
						},
					},
				},
			},
		}),
	)
	api := newTestAPI(client, supported())

	page, err := api.WarmStartPage(
		context.Background(), 200, nil, []string{"loss", "accuracy"})

	require.NoError(t, err)
	require.Len(t, page.Runs, 1)
	assert.JSONEq(
		t,
		`[{"loss": 1.0, "accuracy": 0.9, "_step": 0}]`,
		page.Runs[0].HistoryJSON,
	)

	gqlmock.AssertVariables(
		t,
		client.AllRequests()[0],
		gqlmock.GQLVar(
			"historySpecs", historySpecsWantKeys("loss", "accuracy", "_step"),
		),
	)
}

func TestWarmStartPageWithoutMetricSkipsHistory(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		mustJSON(t, gql.SweepRunsWithHistoryResponse{
			Project: &gql.SweepRunsWithHistoryProject{
				Sweep: &gql.SweepRunsWithHistoryProjectSweep{
					State: "RUNNING",
					Runs: gql.SweepRunsWithHistoryProjectSweepRunsRunConnection{
						SweepPollRuns: gql.SweepPollRuns{
							PageInfo: gql.SweepPollRunsPageInfo{
								HasNextPage: false,
								EndCursor:   nil,
							},
							Edges: []gql.SweepPollRunsEdgesRunEdge{
								{
									Node: gql.SweepPollRunsEdgesRunEdgeNodeRun{
										Id:             "UnVuOjE=",
										Name:           "run-1",
										State:          nullify.NilIfZero("finished"),
										Config:         nullify.NilIfZero("{}"),
										SummaryMetrics: nullify.NilIfZero("{}"),
										SampledHistory: []interface{}{},
									},
								},
							},
						},
					},
				},
			},
		}),
	)
	api := newTestAPI(client, supported())

	page, err := api.WarmStartPage(context.Background(), 200, nil, nil)

	require.NoError(t, err)
	assert.Nil(t, page.NextCursor)
	require.Len(t, page.Runs, 1)
	assert.Equal(t, "", page.Runs[0].HistoryJSON)
}

func TestWarmStartPageSweepNotFound(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		mustJSON(t, gql.SweepRunsWithHistoryResponse{Project: nil}),
	)
	api := newTestAPI(client, supported())

	_, err := api.WarmStartPage(context.Background(), 200, nil, []string{"loss"})

	assert.ErrorIs(t, err, scheduler.ErrSweepNotFound)
}

func TestFetchWatchedRuns(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepWatchedRuns"),
		mustJSON(t, gql.SweepWatchedRunsResponse{
			Project: &gql.SweepWatchedRunsProject{
				Sweep: &gql.SweepWatchedRunsProjectSweep{State: "RUNNING"},
				Runs: &gql.SweepWatchedRunsProjectRunsRunConnection{
					SweepPollRuns: gql.SweepPollRuns{
						PageInfo: gql.SweepPollRunsPageInfo{
							HasNextPage: true,
							EndCursor:   nullify.NilIfZero("abc"),
						},
						Edges: []gql.SweepPollRunsEdgesRunEdge{
							{
								Node: gql.SweepPollRunsEdgesRunEdgeNodeRun{
									Id:             "UnVuOjE=",
									Name:           "run-1",
									State:          nullify.NilIfZero("running"),
									Config:         nullify.NilIfZero(`{"param1": {"value": 1}}`),
									SummaryMetrics: nullify.NilIfZero(`{"loss": 0.5}`),
									SampledHistory: []interface{}{
										[]interface{}{
											map[string]interface{}{"loss": 1.0, "_step": 0},
										},
									},
								},
							},
						},
					},
				},
			},
		}),
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
	)
}

func TestFetchWatchedRunsSweepNotFound(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("SweepWatchedRuns"),
		mustJSON(t, gql.SweepWatchedRunsResponse{
			Project: &gql.SweepWatchedRunsProject{Sweep: nil, Runs: nil},
		}),
	)
	api := newTestAPI(client, supported())

	_, err := api.FetchWatchedRuns(
		context.Background(), []string{"run-1"}, 200, nil, nil)

	assert.ErrorIs(t, err, scheduler.ErrSweepNotFound)
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

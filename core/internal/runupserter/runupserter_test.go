package runupserter_test

import (
	"context"
	"errors"
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/waitingtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"go.uber.org/mock/gomock"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

// runRecord returns a Record with the run field set.
func runRecord(run *spb.RunRecord) *spb.Record {
	return &spb.Record{
		RecordType: &spb.Record_Run{
			Run: run,
		},
	}
}

// testParams returns upserter parameters with default values for testing.
func testParams() runupserter.RunUpserterParams {
	return runupserter.RunUpserterParams{
		DebounceDelay:   waiting.NoDelay(),
		Settings:        settings.New(),
		BeforeRunEndCtx: context.Background(),
		Operations:      nil,
		FeatureProvider: featurechecker.NewServerFeaturesCachePreloaded(
			map[spb.ServerFeature]featurechecker.Feature{},
		),
		GraphqlClientOrNil: nil,
		Logger:             observability.NewNoOpLogger(),
		ClientID:           "test",
	}
}

// fakeUpsertBucketResponseJSON returns a fake UpsertBucket response.
func fakeUpsertBucketResponseJSON() string {
	return `{
		"upsertBucket": {
			"bucket": {
				"id": "storage ID",
				"name": "run ID",
				"displayName": "display name",
				"sweepName": "sweep ID",
				"project": {
					"name": "project name",
					"entity": {"name": "entity name"}
				}
			}
		}
	}`
}

func TestInitRun_MakesCorrectRequest(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	params := testParams()
	params.GraphqlClientOrNil = mockClient
	params.Settings = settings.From(&spb.Settings{
		Program: wrapperspb.String("program"),
	})
	mockClient.StubMatchOnce(
		gqlmock.WithOpName("UpsertBucket"),
		fakeUpsertBucketResponseJSON(),
	)

	upserter, _ := runupserter.InitRun(
		runRecord(&spb.RunRecord{
			// In order of UpsertBucket parameters.
			StorageId:   "storage ID",
			RunId:       "run ID",
			Project:     "project name",
			Entity:      "entity name",
			RunGroup:    "group name",
			DisplayName: "display name",
			Notes:       "notes",
			Git: &spb.GitRepoRecord{
				Commit:    "commit",
				RemoteUrl: "remote URL", // repo parameter
			},
			Config: &spb.ConfigRecord{
				Update: []*spb.ConfigItem{{
					Key:       "test",
					ValueJson: `123`,
				}},
			},
			Telemetry: &spb.TelemetryRecord{PythonVersion: "test python"},
			Host:      "host",
			JobType:   "job type",
			SweepId:   "sweep ID",
			Tags:      []string{"tag1", "tag2"},
		}),
		params,
	)
	defer upserter.Finish()

	requests := mockClient.AllRequests()
	assert.Len(t, requests, 1)
	gqlmock.AssertVariables(
		t,
		requests[0],
		gqlmock.GQLVar("id", gomock.Eq("storage ID")),
		gqlmock.GQLVar("name", gomock.Eq("run ID")),
		gqlmock.GQLVar("project", gomock.Eq("project name")),
		gqlmock.GQLVar("entity", gomock.Eq("entity name")),
		gqlmock.GQLVar("groupName", gomock.Eq("group name")),
		gqlmock.GQLVar("displayName", gomock.Eq("display name")),
		gqlmock.GQLVar("notes", gomock.Eq("notes")),
		gqlmock.GQLVar("commit", gomock.Eq("commit")),
		gqlmock.GQLVar("config", gqlmock.JSONEq(fmt.Sprintf(`
				{
					"test": {"value": 123},
					"_wandb": {"value": {
						"python_version": "test python",
						"m": [],
						"t": {
							"4": "test python",
							"12": "%s"
						}
					}}
				}
			`, version.Version))),
		gqlmock.GQLVar("host", gomock.Eq("host")),
		gqlmock.GQLVar("program", gomock.Eq("program")),
		gqlmock.GQLVar("repo", gomock.Eq("remote URL")),
		gqlmock.GQLVar("jobType", gomock.Eq("job type")),
		gqlmock.GQLVar("sweep", gomock.Eq("sweep ID")),
		gqlmock.GQLVar("tags", gomock.Eq([]any{"tag1", "tag2"})))
}

func TestInitRun_ReadsResponse(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	params := testParams()
	params.GraphqlClientOrNil = mockClient
	mockClient.StubMatchOnce(
		gqlmock.WithOpName("UpsertBucket"),
		`{
			"upsertBucket": {
				"bucket": {
					"id": "storage ID",
					"name": "run ID",
					"displayName": "display name",
					"sweepName": "sweep ID",
					"project": {
						"name": "project name",
						"entity": {"name": "entity name"}
					}
				}
			}
		}`,
	)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.Nil(t, err)
	assert.Equal(t, "storage ID", run.StorageId)
	assert.Equal(t, "run ID", run.RunId)
	assert.Equal(t, "display name", run.DisplayName)
	assert.Equal(t, "sweep ID", run.SweepId)
	assert.Equal(t, "project name", run.Project)
	assert.Equal(t, "entity name", run.Entity)
}

func TestInitRun_UpsertError(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	params := testParams()
	params.GraphqlClientOrNil = mockClient
	mockClient.StubMatchWithError(
		gqlmock.WithOpName("UpsertBucket"),
		errors.New("test error"),
	)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)

	assert.Nil(t, upserter)
	assert.ErrorContains(t, err, "test error")
}

func TestInitRun_Offline(t *testing.T) {
	params := testParams()
	params.GraphqlClientOrNil = nil

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	defer upserter.Finish()

	assert.Nil(t, err)
	assert.NotNil(t, upserter)
}

func TestResume(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	mockClient.StubMatchOnce(gqlmock.WithOpName("RunResumeStatus"), `{}`)
	mockClient.StubMatchOnce(
		gqlmock.WithOpName("UpsertBucket"),
		fakeUpsertBucketResponseJSON(),
	)

	params := testParams()
	params.GraphqlClientOrNil = mockClient
	params.Settings = settings.From(&spb.Settings{Resume: wrapperspb.String("allow")})

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	defer upserter.Finish()

	assert.NoError(t, err)
	assert.True(t, mockClient.AllStubsUsed())
}

func TestResume_Offline_Succeeds(t *testing.T) {
	params := testParams()
	params.GraphqlClientOrNil = nil
	params.Settings = settings.From(&spb.Settings{Resume: wrapperspb.String("must")})

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	defer upserter.Finish()

	assert.NoError(t, err)
}

func TestRewind(t *testing.T) {
	// NOTE: Rewinding works offline.
	runInitRecord := runRecord(
		&spb.RunRecord{
			RunId: "run to rewind",
			BranchPoint: &spb.BranchPoint{
				Run:    "run to rewind",
				Metric: "_step",
				Value:  123,
			},
		})

	upserter, err := runupserter.InitRun(runInitRecord, testParams())
	defer upserter.Finish()

	assert.NoError(t, err)
	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.EqualValues(t, run.StartingStep, 124)
}

func TestFork(t *testing.T) {
	// NOTE: Forking works offline.
	runInitRecord := runRecord(
		&spb.RunRecord{
			RunId: "run",
			BranchPoint: &spb.BranchPoint{
				Run:    "other run",
				Metric: "_step",
				Value:  10,
			},
		},
	)

	upserter, err := runupserter.InitRun(runInitRecord, testParams())
	defer upserter.Finish()

	assert.NoError(t, err)
	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.EqualValues(t, run.StartingStep, 11)
}

type variablesForUpdateTest struct {
	MockClient    *gqlmock.MockClient
	DebounceDelay *waitingtest.FakeDelay
	Upserter      *runupserter.RunUpserter
}

// setupUpdateTest returns an initialized RunUpserter and a mock GraphQL client
// stubbed to expect one more UpsertBucket request.
func setupUpdateTest(t *testing.T) variablesForUpdateTest {
	t.Helper()

	params := testParams()
	fakeDebounceDelay := waitingtest.NewFakeDelay()
	mockClient := gqlmock.NewMockClient()
	params.DebounceDelay = fakeDebounceDelay
	params.GraphqlClientOrNil = mockClient

	// There will be two upserts: the initial one, and a single update.
	for range 2 {
		mockClient.StubMatchOnce(
			gqlmock.WithOpName("UpsertBucket"),
			fakeUpsertBucketResponseJSON(),
		)
	}

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)

	require.NoError(t, err)
	return variablesForUpdateTest{
		MockClient:    mockClient,
		DebounceDelay: fakeDebounceDelay,
		Upserter:      upserter,
	}
}

func TestUpdate_Debounces(t *testing.T) {
	vars := setupUpdateTest(t)

	vars.Upserter.Update(&spb.RunRecord{})
	vars.Upserter.UpdateConfig(&spb.ConfigRecord{})
	vars.Upserter.UpdateTelemetry(&spb.TelemetryRecord{})
	vars.Upserter.UpdateMetrics(&spb.MetricRecord{})
	vars.DebounceDelay.WaitAndTick(t, true /*allowMoreWait*/, time.Second)
	vars.Upserter.Finish()

	requests := vars.MockClient.AllRequests()
	assert.Len(t, requests, 2)
}

func TestUpdate_Uploads(t *testing.T) {
	vars := setupUpdateTest(t)

	vars.Upserter.Update(&spb.RunRecord{RunId: "test run ID"})
	vars.DebounceDelay.WaitAndTick(t, true /*allowMoreWait*/, time.Second)
	vars.Upserter.Finish()

	requests := vars.MockClient.AllRequests()
	assert.Len(t, requests, 2)
	gqlmock.AssertVariables(t,
		requests[1],
		gqlmock.GQLVar("name", gomock.Eq("test run ID")),
		gqlmock.GQLVar("config", gomock.Eq(nil)))
}

func TestUpdateConfig_Uploads(t *testing.T) {
	vars := setupUpdateTest(t)

	vars.Upserter.UpdateConfig(
		&spb.ConfigRecord{
			Update: []*spb.ConfigItem{{
				Key:       "test key",
				ValueJson: `"test value"`,
			}},
		},
	)
	vars.DebounceDelay.WaitAndTick(t, true /*allowMoreWait*/, time.Second)
	vars.Upserter.Finish()

	requests := vars.MockClient.AllRequests()
	assert.Len(t, requests, 2)
	gqlmock.AssertVariables(t,
		requests[1],
		gqlmock.GQLVar("config", gqlmock.JSONEq(fmt.Sprintf(`
				{
					"_wandb": {"value": {"m": [], "t": {"12": "%s"}}},
					"test key": {"value": "test value"}
				}
			`, version.Version))))
}

func TestUpdateEnvironment_Uploads(t *testing.T) {
	vars := setupUpdateTest(t)

	vars.Upserter.UpdateEnvironment(
		&spb.EnvironmentRecord{
			WriterId: "test",
		},
	)
	vars.DebounceDelay.WaitAndTick(t, true /*allowMoreWait*/, time.Second)
	vars.Upserter.Finish()

	requests := vars.MockClient.AllRequests()
	assert.Len(t, requests, 2)
	gqlmock.AssertVariables(t,
		requests[1],
		gqlmock.GQLVar("config", gqlmock.JSONEq(fmt.Sprintf(`
				{
					"_wandb": {"value": {"m": [], "e": {"test": {"writerId": "test"}}, "t": {"12": "%s"}}}
				}
			`, version.Version))))
}

func TestUpdateTelemetry_Uploads(t *testing.T) {
	vars := setupUpdateTest(t)

	vars.Upserter.UpdateTelemetry(
		&spb.TelemetryRecord{PythonVersion: "test python version"},
	)
	vars.DebounceDelay.WaitAndTick(t, true /*allowMoreWait*/, time.Second)
	vars.Upserter.Finish()

	requests := vars.MockClient.AllRequests()
	assert.Len(t, requests, 2)
	gqlmock.AssertVariables(t,
		requests[1],
		gqlmock.GQLVar("config", gqlmock.JSONEq(fmt.Sprintf(`
				{
					"_wandb": {"value": {
						"python_version": "test python version",
						"m": [],
						"t": {
							"4": "test python version",
							"12": "%s"
						}
					}}
				}
			`, version.Version))))
}

func TestUpdateMetrics_Uploads(t *testing.T) {
	vars := setupUpdateTest(t)

	vars.Upserter.UpdateMetrics(&spb.MetricRecord{Name: "test metric"})
	vars.DebounceDelay.WaitAndTick(t, true /*allowMoreWait*/, time.Second)
	vars.Upserter.Finish()

	requests := vars.MockClient.AllRequests()
	assert.Len(t, requests, 2)
	gqlmock.AssertVariables(t,
		requests[1],
		gqlmock.GQLVar("config", gqlmock.JSONEq(fmt.Sprintf(`
				{
					"_wandb": {"value": {
						"m": [{"1": "test metric", "6": [3], "7": []}],
						"t": {"12": "%s"}
					}}
				}
			`, version.Version))))
}

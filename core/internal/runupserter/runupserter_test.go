package runupserter_test

import (
	"context"
	"fmt"
	"path/filepath"
	"testing"
	"testing/synctest"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/vektah/gqlparser/v2/gqlerror"
	"go.uber.org/mock/gomock"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runsyncstate"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/runupsertertest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/version"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
func testParams(t *testing.T) runupserter.RunUpserterParams {
	t.Helper()
	tempRunDir := t.TempDir()
	syncStateStore := runsyncstate.File(filepath.Join(tempRunDir, "run.wandb"))
	return runupserter.RunUpserterParams{
		Settings:           settings.New(),
		BeforeRunEndCtx:    context.Background(),
		Operations:         nil,
		FeatureProvider:    featurechecker.NewPreloaded(nil),
		GraphqlClientOrNil: nil,
		Logger:             observabilitytest.NewTestLogger(t),
		ClientID:           "test",
		SyncStateStore:     syncStateStore,
	}
}

func TestInitRun_MakesCorrectRequest(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	params := testParams(t)
	params.GraphqlClientOrNil = mockClient
	params.Settings = settings.From(&spb.Settings{
		Program: wrapperspb.String("program"),
	})
	mockClient.StubMatchOnce(gqlmock.WithOpName("RunResumeStatus"), `{}`)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(
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
	require.NoError(t, err)
	defer upserter.Finish()

	requests := mockClient.AllRequests()
	require.Len(t, requests, 1)
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
	params := testParams(t)
	params.GraphqlClientOrNil = mockClient
	mockClient.StubMatchOnce(gqlmock.WithOpName("RunResumeStatus"), `{}`)
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
	require.NoError(t, err)
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
	params := testParams(t)
	params.GraphqlClientOrNil = mockClient
	mockClient.StubMatchOnce(gqlmock.WithOpName("RunResumeStatus"), `{}`)
	mockClient.StubMatchWithError(
		gqlmock.WithOpName("UpsertBucket"),
		&graphql.HTTPError{
			StatusCode: 500,
			Response: graphql.Response{
				Errors: gqlerror.List{
					{Message: "Everything is broken"},
				},
			},
		},
	)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)

	assert.Nil(t, upserter)
	runUpdateError := err.(*runupserter.RunUpdateError)
	assert.Equal(t, "Everything is broken", runUpdateError.UserMessage)
}

func TestInitRun_InitTimeout(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		mockClient := gqlmock.NewMockClient()
		params := testParams(t)
		params.GraphqlClientOrNil = mockClient
		params.Settings = settings.From(&spb.Settings{
			InitTimeout: wrapperspb.Double(10),
		})
		mockClient.StubMatchHang(gqlmock.WithOpName("UpsertBucket"))

		upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)

		assert.Nil(t, upserter)
		assert.ErrorContains(t, err, "context deadline exceeded")
	})
}

func TestInitRun_NoInitTimeout_Waits(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		mockClient := gqlmock.NewMockClient()
		params := testParams(t)
		params.GraphqlClientOrNil = mockClient
		beforeRunEndCtx, cancel := context.WithCancel(context.Background())
		params.BeforeRunEndCtx = beforeRunEndCtx
		mockClient.StubMatchHang(gqlmock.WithOpName("UpsertBucket"))

		done := make(chan struct{})
		go func() {
			defer close(done)
			_, _ = runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
		}()

		// Without an init timeout (as during `wandb sync`), InitRun blocks
		// on the request indefinitely rather than timing out.
		time.Sleep(time.Hour)
		select {
		case <-done:
			t.Error("InitRun returned despite no init timeout")
		default:
		}

		cancel()
		<-done
	})
}

func TestInitRun_Offline(t *testing.T) {
	params := testParams(t)
	params.GraphqlClientOrNil = nil

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	require.NoError(t, err)
	upserter.Finish()
}

func setupResumeTest(
	t *testing.T,
	resume string,
) (*gqlmock.MockClient, runupserter.RunUpserterParams) {
	t.Helper()
	mockClient := gqlmock.NewMockClient()
	params := testParams(t)
	params.GraphqlClientOrNil = mockClient
	if resume != "" {
		params.Settings = settings.From(&spb.Settings{Resume: wrapperspb.String(resume)})
	}
	return mockClient, params
}

func assertResumeInitErrorContains(
	t *testing.T,
	upserter *runupserter.RunUpserter,
	err error,
	wantContains string,
) {
	t.Helper()
	assert.Nil(t, upserter)
	runUpdateError := err.(*runupserter.RunUpdateError)
	assert.Contains(t, runUpdateError.UserMessage, wantContains)
}

func TestResume_ResumeModeTrue_Allow(t *testing.T) {
	mockClient, params := setupResumeTest(t, "allow")
	mockClient.StubMatchOnce(gqlmock.WithOpName("RunResumeStatus"), `{}`)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(
		runRecord(&spb.RunRecord{ResumeMode: true}),
		params,
	)
	require.NoError(t, err)
	defer upserter.Finish()
	assert.True(t, mockClient.AllStubsUsed())
}

func TestResume_ResumeModeTrueSettingNever_RejectsExistingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "never")
	runupsertertest.StubRunResumeStatusExistingRun(t, mockClient)

	upserter, err := runupserter.InitRun(
		runRecord(&spb.RunRecord{RunId: "run", ResumeMode: true}),
		params,
	)
	assertResumeInitErrorContains(
		t,
		upserter,
		err,
		"does not allow resuming an existing run",
	)
	assert.True(t, mockClient.AllStubsUsed())
}

func TestResume_ResumeModeTrueSettingEmpty_ReconcilesServerStartingStep(t *testing.T) {
	// `wandb beta sync` does not pass a resume setting; reconciliation relies
	// on ResumeMode recorded in the transaction log at wandb.init() time.
	mockClient, params := setupResumeTest(t, "")
	runupsertertest.StubRunResumeStatusWithStep(t, mockClient, 4)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(
		runRecord(&spb.RunRecord{RunId: "run", ResumeMode: true}),
		params,
	)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.EqualValues(t, 5, run.StartingStep)
	assert.True(t, mockClient.AllStubsUsed())
}

func TestResume_ResumeSettingNeverNoResumeMode_RejectsExistingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "never")
	runupsertertest.StubRunResumeStatusExistingRun(t, mockClient)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{RunId: "run"}), params)
	assertResumeInitErrorContains(
		t,
		upserter,
		err,
		"does not allow resuming an existing run",
	)
	assert.True(t, mockClient.AllStubsUsed())
}

// This verifies the correct error handling for missing run and ResumeMode=False.
func TestResume_ResumeModeFalseSettingAllow_AllowsMissingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "allow")
	mockClient.StubMatchOnce(gqlmock.WithOpName("RunResumeStatus"), `{}`)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.True(t, run.ResumeMode)
	assert.True(t, mockClient.AllStubsUsed())
}

func TestResume_ResumeModeFalseSettingMust_RejectsMissingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "must")
	mockClient.StubMatchOnce(gqlmock.WithOpName("RunResumeStatus"), `{}`)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	assertResumeInitErrorContains(
		t,
		upserter,
		err,
		"requires an existing run to resume",
	)
	assert.True(t, mockClient.AllStubsUsed())
}

func TestResume_ResumeModeFalseSettingNever_AllowsMissingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "never")
	mockClient.StubMatchOnce(gqlmock.WithOpName("RunResumeStatus"), `{}`)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.False(t, run.ResumeMode)
	assert.True(t, mockClient.AllStubsUsed())
}

func TestResume_ResumeModeFalseSettingUnset_AllowsMissingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "")
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.False(t, run.ResumeMode)
	assert.True(t, mockClient.AllStubsUsed())
}

func TestResume_ResumeModeFalseSettingAuto_AllowsMissingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "auto")
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.False(t, run.ResumeMode)
	assert.True(t, mockClient.AllStubsUsed())
}

func TestResume_ResumeModeFalseSettingUnexpected_AllowsMissingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "unexpected")
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.False(t, run.ResumeMode)
	assert.True(t, mockClient.AllStubsUsed())
}

// This test proves that ResumeMode=False (equivalent to `resume=never`) can be
// overridden by explicitly setting `resume=allow` or `resume=must` when there
// is an existing run.
func TestResume_ResumeModeFalseSettingAllow_AllowsExistingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "allow")
	runupsertertest.StubRunResumeStatusExistingRun(t, mockClient)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{RunId: "run"}), params)
	require.NoError(t, err)
	defer upserter.Finish()
	assert.True(t, mockClient.AllStubsUsed())
}

func TestResume_ResumeModeFalseSettingMust_AllowsExistingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "must")
	runupsertertest.StubRunResumeStatusExistingRun(t, mockClient)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{RunId: "run"}), params)
	require.NoError(t, err)
	defer upserter.Finish()
	assert.True(t, mockClient.AllStubsUsed())
}

func TestResume_Offline_SettingsOverrideMissingRunIntent(t *testing.T) {
	params := testParams(t)
	params.GraphqlClientOrNil = nil
	params.Settings = settings.From(&spb.Settings{Resume: wrapperspb.String("must")})

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.True(t, run.ResumeMode)
}

func TestResume_Offline_PreservesRunRecordIntent(t *testing.T) {
	params := testParams(t)
	params.GraphqlClientOrNil = nil
	params.Settings = settings.From(&spb.Settings{Resume: wrapperspb.String("must")})

	upserter, err := runupserter.InitRun(
		runRecord(&spb.RunRecord{ResumeMode: true}),
		params,
	)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.True(t, run.ResumeMode)
}

func TestResume_InitializesSyncStateStartingStep(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	runupsertertest.StubRunResumeStatusWithStep(t, mockClient, 4)
	runupsertertest.StubUpsertBucket(t, mockClient)

	params := testParams(t)
	params.GraphqlClientOrNil = mockClient
	params.Settings = settings.From(&spb.Settings{Resume: wrapperspb.String("allow")})

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{RunId: "run"}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.EqualValues(t, 5, run.StartingStep)
	startingStep, err := params.SyncStateStore.GetOrInitStartingStep(0)
	require.NoError(t, err)
	assert.EqualValues(t, 5, startingStep)
}

func TestResume_ReusesSyncStateStartingStep(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	runupsertertest.StubRunResumeStatusWithStep(t, mockClient, 99)
	runupsertertest.StubUpsertBucket(t, mockClient)

	startingStep := int64(6)
	params := testParams(t)
	_, err := params.SyncStateStore.GetOrInitStartingStep(startingStep)
	require.NoError(t, err)
	params.GraphqlClientOrNil = mockClient
	params.Settings = settings.From(&spb.Settings{Resume: wrapperspb.String("allow")})

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{RunId: "run"}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	// Even though the live query resolves _step=99, as if a previous sync
	// already uploaded more history, the pre-initialized value wins so that
	// re-syncing doesn't shift steps forward.
	assert.EqualValues(t, 6, run.StartingStep)
}

func TestResume_KeepsEventsAndOutputFileStreamOffsets(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	mockClient.StubMatchOnce(gqlmock.WithOpName("RunResumeStatus"), `{
		"model": {
			"bucket": {
				"name": "run",
				"id": "storage-id",
				"historyLineCount": 3,
				"eventsLineCount": 13,
				"logLineCount": 15,
				"historyTail": "[]",
				"summaryMetrics": "{}",
				"config": "{}",
				"eventsTail": "[]",
				"wandbConfig": "{\"t\": 1}"
			}
		}
	}`)
	mockClient.StubMatchOnce(gqlmock.WithOpName("UpsertBucket"), `{
		"upsertBucket": {
			"bucket": {
				"id": "storage ID",
				"name": "run ID",
				"displayName": "display name",
				"sweepName": "sweep ID",
				"project": {
					"name": "project name",
					"entity": {"name": "entity name"}
				},
				"historyLineCount": 5
			}
		}
	}`)

	params := testParams(t)
	params.GraphqlClientOrNil = mockClient
	params.Settings = settings.From(&spb.Settings{Resume: wrapperspb.String("allow")})

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{RunId: "run"}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	assert.Equal(t,
		filestream.FileStreamOffsetMap{
			filestream.HistoryChunk: 5,
			filestream.EventsChunk:  13,
			filestream.OutputChunk:  15,
		},
		upserter.FileStreamOffsets())
}

func TestOfflineResume_DoesNotInitializeSyncStateStartingStep(t *testing.T) {
	// An offline run cannot reconcile resume state with the backend, so it
	// must not save a starting step: `wandb sync` computes the real one and
	// would otherwise reuse the offline placeholder and re-upload the
	// segment starting at step 0.
	offlineParams := testParams(t)
	offlineParams.Settings = settings.From(&spb.Settings{
		Resume:   wrapperspb.String("must"),
		XOffline: wrapperspb.Bool(true),
	})

	offline, err := runupserter.InitRun(
		runRecord(&spb.RunRecord{RunId: "run"}), offlineParams)
	require.NoError(t, err)
	offline.Finish()

	// Simulate `wandb sync` on the same run directory.
	mockClient := gqlmock.NewMockClient()
	runupsertertest.StubRunResumeStatusWithStep(t, mockClient, 4)
	runupsertertest.StubUpsertBucket(t, mockClient)
	syncParams := testParams(t)
	syncParams.SyncStateStore = offlineParams.SyncStateStore
	syncParams.GraphqlClientOrNil = mockClient
	syncParams.Settings = settings.From(&spb.Settings{Resume: wrapperspb.String("must")})

	upserter, err := runupserter.InitRun(
		runRecord(&spb.RunRecord{RunId: "run"}), syncParams)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.EqualValues(t, 5, run.StartingStep)
}

func TestNewRun_InitializesSyncStateStartingStep(t *testing.T) {
	mockClient := gqlmock.NewMockClient()
	runupsertertest.StubUpsertBucket(t, mockClient)

	params := testParams(t)
	params.GraphqlClientOrNil = mockClient

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{RunId: "run"}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.EqualValues(t, 0, run.StartingStep)
	startingStep, err := params.SyncStateStore.GetOrInitStartingStep(1)
	require.NoError(t, err)
	assert.EqualValues(t, 0, startingStep)
}

func TestRewind_InitializesSyncStateStartingStep(t *testing.T) {
	runInitRecord := runRecord(
		&spb.RunRecord{
			RunId: "run to rewind",
			BranchPoint: &spb.BranchPoint{
				Run:    "run to rewind",
				Metric: "_step",
				Value:  123,
			},
		})

	mockClient := gqlmock.NewMockClient()
	mockClient.StubMatchOnce(gqlmock.WithOpName("RewindRun"), `{
		"rewindRun": {
			"rewoundRun": {
				"id": "storage ID",
				"name": "run to rewind"
			}
		}
	}`)
	runupsertertest.StubUpsertBucket(t, mockClient)

	params := testParams(t)
	params.GraphqlClientOrNil = mockClient
	params.Settings = settings.From(&spb.Settings{Resume: wrapperspb.String("must")})
	upserter, err := runupserter.InitRun(runInitRecord, params)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.EqualValues(t, run.StartingStep, 124)
	startingStep, err := params.SyncStateStore.GetOrInitStartingStep(0)
	require.NoError(t, err)
	assert.EqualValues(t, 124, startingStep)
}

func TestFork_InitializesSyncStateStartingStep(t *testing.T) {
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

	mockClient := gqlmock.NewMockClient()
	runupsertertest.StubUpsertBucket(t, mockClient)

	params := testParams(t)
	params.GraphqlClientOrNil = mockClient
	params.Settings = settings.From(&spb.Settings{Resume: wrapperspb.String("must")})

	upserter, err := runupserter.InitRun(runInitRecord, params)
	require.NoError(t, err)
	defer upserter.Finish()

	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	assert.EqualValues(t, run.StartingStep, 11)
	startingStep, err := params.SyncStateStore.GetOrInitStartingStep(0)
	require.NoError(t, err)
	assert.EqualValues(t, 11, startingStep)
}

type variablesForUpdateTest struct {
	MockClient *gqlmock.MockClient
	Upserter   *runupserter.RunUpserter
}

// setupUpdateTest returns an initialized RunUpserter and a mock GraphQL client
// stubbed to expect one more UpsertBucket request.
func setupUpdateTest(t *testing.T) variablesForUpdateTest {
	t.Helper()

	params := testParams(t)
	mockClient := gqlmock.NewMockClient()
	params.DebounceDelay = 5 * time.Second // just needs to be >0 for tests
	params.GraphqlClientOrNil = mockClient

	// There will be two upserts: the initial one, and a single update.
	mockClient.StubMatchOnce(gqlmock.WithOpName("RunResumeStatus"), `{}`)
	runupsertertest.StubUpsertBucket(t, mockClient)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{}), params)

	require.NoError(t, err)
	return variablesForUpdateTest{
		MockClient: mockClient,
		Upserter:   upserter,
	}
}

func TestUpdate_Debounces(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		vars := setupUpdateTest(t)

		vars.Upserter.Update(&spb.RunRecord{})
		vars.Upserter.UpdateConfig(&spb.ConfigRecord{})
		vars.Upserter.UpdateTelemetry(&spb.TelemetryRecord{})
		vars.Upserter.UpdateMetrics(&spb.MetricRecord{})
		vars.Upserter.Finish()

		requests := vars.MockClient.AllRequests()
		assert.Len(t, requests, 2)
	})
}

func TestUpdate_Uploads(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		vars := setupUpdateTest(t)

		vars.Upserter.Update(&spb.RunRecord{RunId: "test run ID"})
		vars.Upserter.Finish()

		requests := vars.MockClient.AllRequests()
		require.Len(t, requests, 2)
		gqlmock.AssertVariables(t,
			requests[1],
			gqlmock.GQLVar("name", gomock.Eq("test run ID")),
			gqlmock.GQLVar("config", gomock.Eq(nil)))
	})
}

func TestUpdateConfig_Uploads(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		vars := setupUpdateTest(t)

		vars.Upserter.UpdateConfig(
			&spb.ConfigRecord{
				Update: []*spb.ConfigItem{{
					Key:       "test key",
					ValueJson: `"test value"`,
				}},
			},
		)
		vars.Upserter.Finish()

		requests := vars.MockClient.AllRequests()
		require.Len(t, requests, 2)
		gqlmock.AssertVariables(t,
			requests[1],
			gqlmock.GQLVar("config", gqlmock.JSONEq(fmt.Sprintf(`
					{
						"_wandb": {"value": {"m": [], "t": {"12": "%s"}}},
						"test key": {"value": "test value"}
					}
				`, version.Version))))
	})
}

func TestUpdateEnvironment_Uploads(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		vars := setupUpdateTest(t)

		vars.Upserter.UpdateEnvironment(
			&spb.EnvironmentRecord{
				WriterId: "test",
			},
		)
		vars.Upserter.Finish()

		requests := vars.MockClient.AllRequests()
		require.Len(t, requests, 2)
		gqlmock.AssertVariables(t,
			requests[1],
			gqlmock.GQLVar("config", gqlmock.JSONEq(fmt.Sprintf(`
					{
						"_wandb": {"value": {"m": [], "e": {"test": {"writerId": "test"}}, "t": {"12": "%s"}}}
					}
				`, version.Version))))
	})
}

func TestUpdateTelemetry_Uploads(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		vars := setupUpdateTest(t)

		vars.Upserter.UpdateTelemetry(
			&spb.TelemetryRecord{PythonVersion: "test python version"},
		)
		vars.Upserter.Finish()

		requests := vars.MockClient.AllRequests()
		require.Len(t, requests, 2)
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
	})
}

func TestUpdateMetrics_Uploads(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		vars := setupUpdateTest(t)

		vars.Upserter.UpdateMetrics(&spb.MetricRecord{Name: "test metric"})
		vars.Upserter.Finish()

		requests := vars.MockClient.AllRequests()
		require.Len(t, requests, 2)
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
	})
}

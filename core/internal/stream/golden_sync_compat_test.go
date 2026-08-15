package stream_test

import (
	"context"
	"encoding/json"
	"strconv"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filestreamtest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runsyncstate"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/runupsertertest"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type goldenSenderFixtures struct {
	Sender     *stream.Sender
	FileStream *filestreamtest.FakeFileStream
	Settings   *wbsettings.Settings
}

func makeGoldenSender(
	t *testing.T,
	mockGQL *gqlmock.MockClient,
	fixture string,
) goldenSenderFixtures {
	return makeGoldenSenderWithSharedFlag(t, mockGQL, fixture, true)
}

func makeGoldenSenderWithSharedFlag(
	t *testing.T,
	mockGQL *gqlmock.MockClient,
	fixture string,
	keepSharedFlag bool,
) goldenSenderFixtures {
	t.Helper()

	records := transactionlogtest.GoldenLogRecords(t, fixture)
	var runRecord *spb.RunRecord
	for _, record := range records {
		if run := record.GetRun(); run != nil {
			runRecord = run
			break
		}
	}
	require.NotNil(t, runRecord, "fixture %q must contain a Run record", fixture)
	// TODO: UNCOMMENT THIS AFTER FIXING SHARED MODE
	// if !keepSharedFlag {
	//     runRecord.SharedMode = false
	// }

	if runRecord.GetResumeMode() {
		runupsertertest.StubRunResumeStatusWithStep(t, mockGQL, 4)
		runupsertertest.StubUpsertBucket(t, mockGQL)
	}

	logger := observabilitytest.NewTestLogger(t)
	settings := wbsettings.From(&spb.Settings{
		RunId:   &wrapperspb.StringValue{Value: runRecord.GetRunId()},
		Console: &wrapperspb.StringValue{Value: "off"},
		ApiKey:  &wrapperspb.StringValue{Value: "test-api-key"},
	})

	params := runupserter.RunUpserterParams{
		Logger:          logger,
		Settings:        settings,
		FeatureProvider: featurechecker.NewPreloaded(nil),
		BeforeRunEndCtx: context.Background(),
		ClientID:        "test-client-id",
		SyncStateStore:  runsyncstate.Noop(),
	}
	if runRecord.GetResumeMode() {
		params.GraphqlClientOrNil = mockGQL
	}

	upserter, err := runupserter.InitRun(
		&spb.Record{RecordType: &spb.Record_Run{Run: runRecord}},
		params,
	)
	require.NoError(t, err)

	runHandle := runhandle.New()
	require.NoError(t, runHandle.Init(upserter))

	x := makeSenderWithSettings(t, mockGQL, settings)
	fakeFS := filestreamtest.NewFakeFileStream()
	x.Sender.SetFileStreamForTest(fakeFS)
	x.Sender.SetRunHandleForTest(runHandle)

	for _, record := range records {
		if record.GetHistory() != nil {
			x.Sender.SendRecord(record, nil)
		}
	}

	return goldenSenderFixtures{
		Sender:     x.Sender,
		FileStream: fakeFS,
		Settings:   settings,
	}
}

func historyStepsFromLines(t *testing.T, lines []string) []int64 {
	t.Helper()

	steps := make([]int64, 0, len(lines))
	for i, line := range lines {
		var decoded map[string]any
		require.NoError(t, json.Unmarshal([]byte(line), &decoded), "row %d", i)

		rawStep, ok := decoded["_step"]
		require.True(t, ok, "row %d missing _step: %s", i, line)

		step, err := strconv.ParseInt(
			strconv.FormatFloat(rawStep.(float64), 'f', -1, 64),
			10,
			64,
		)
		require.NoError(t, err)
		steps = append(steps, step)
	}
	return steps
}

func countStepKeysInLine(t *testing.T, line string) int {
	t.Helper()

	var decoded map[string]any
	require.NoError(t, json.Unmarshal([]byte(line), &decoded))
	if _, ok := decoded["_step"]; ok {
		return 1
	}
	return 0
}

func historyLinesHaveNoStep(t *testing.T, lines []string) {
	t.Helper()
	for i, line := range lines {
		assert.Equal(t, 0, countStepKeysInLine(t, line), "row %d", i)
	}
}

func TestSender_GoldenOldFixturesUploadExpectedSteps(t *testing.T) {
	cases := []struct {
		fixture   string
		wantSteps []int64
	}{
		{fixture: "old_auto_steps", wantSteps: []int64{0, 1, 2}},
		{fixture: "old_auto_steps_flat_keys", wantSteps: []int64{0, 1, 2}},
		{fixture: "old_explicit_steps", wantSteps: []int64{0, 5, 10}},
		{fixture: "old_resumed_run", wantSteps: []int64{5, 6, 7}},
	}

	for _, tc := range cases {
		t.Run(tc.fixture, func(t *testing.T) {
			x := makeGoldenSender(t, gqlmock.NewMockClient(), tc.fixture)
			req := x.FileStream.GetRequest(x.Settings)
			assert.Equal(t, tc.wantSteps, historyStepsFromLines(t, req.HistoryLines))
		})
	}
}

func TestSender_GoldenOldNoHistorySyncsCleanly(t *testing.T) {
	x := makeGoldenSender(t, gqlmock.NewMockClient(), "old_no_history")
	req := x.FileStream.GetRequest(x.Settings)
	assert.Empty(t, req.HistoryLines)
}

func TestSender_GoldenOldBadStepTypes_RenumbersUnparseableSteps(t *testing.T) {
	x := makeGoldenSender(t, gqlmock.NewMockClient(), "old_bad_step_types")
	req := x.FileStream.GetRequest(x.Settings)
	require.Len(t, req.HistoryLines, 6)

	assert.Equal(
		t,
		[]int64{0, 1, 2, 3, 4, 5},
		historyStepsFromLines(t, req.HistoryLines),
	)
	for i, line := range req.HistoryLines {
		assert.Equal(t, 1, countStepKeysInLine(t, line), "row %d", i)
	}
}

func TestSender_GoldenNewResumeMode_RebasesFromServerStep(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	x := makeGoldenSender(t, mockGQL, "new_resume_mode")

	req := x.FileStream.GetRequest(x.Settings)
	require.Len(t, req.HistoryLines, 3)
	assert.Equal(t, []int64{5, 6, 7}, historyStepsFromLines(t, req.HistoryLines))
	assert.True(t, mockGQL.AllStubsUsed())
}

func TestSender_GoldenSharedFixturesUploadWithoutStepAxis(t *testing.T) {
	for _, fixture := range []string{"old_shared_mode", "new_shared_mode"} {
		t.Run(fixture, func(t *testing.T) {
			x := makeGoldenSender(t, gqlmock.NewMockClient(), fixture)
			require.True(t, x.Settings.IsSharedMode())

			req := x.FileStream.GetRequest(x.Settings)
			require.NotEmpty(t, req.HistoryLines)
			historyLinesHaveNoStep(t, req.HistoryLines)
		})
	}
}

func TestSender_GoldenSharedFixturesWithoutRunRecordFlagInventsStepAxis(t *testing.T) {
	for _, fixture := range []string{"old_shared_mode", "new_shared_mode"} {
		t.Run(fixture, func(t *testing.T) {
			x := makeGoldenSenderWithSharedFlag(
				t, gqlmock.NewMockClient(), fixture, false /*keepSharedFlag*/)
			require.False(t, x.Settings.IsSharedMode())

			req := x.FileStream.GetRequest(x.Settings)
			require.NotEmpty(t, req.HistoryLines)
			assert.NotEmpty(t, historyStepsFromLines(t, req.HistoryLines))
		})
	}
}

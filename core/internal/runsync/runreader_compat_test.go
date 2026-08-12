package runsync_test

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/runsync"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// TestExtract_OldShapedRunRecordsProduceCorrectRunInfo pins that
// ExtractRunInfo only depends on Entity, Project, RunID, and StartTime, so it
// must succeed unchanged for every RunRecord shape written before offline
// resume: no resume_mode, no starting_step, an online-resumed run, and a
// forked/rewound run.
func TestExtract_OldShapedRunRecordsProduceCorrectRunInfo(t *testing.T) {
	startTime := time.Date(2000, 1, 1, 0, 0, 0, 0, time.UTC)

	tests := []struct {
		name string
		run  *spb.RunRecord
	}{
		{
			name: "PreResumeRunRecord",
			run: &spb.RunRecord{
				Entity:    "test entity",
				Project:   "test project",
				RunId:     "test run ID",
				StartTime: timestamppb.New(startTime),
			},
		},
		{
			name: "OnlineResumedRunRecord",
			run: &spb.RunRecord{
				Entity:       "test entity",
				Project:      "test project",
				RunId:        "test run ID",
				StartTime:    timestamppb.New(startTime),
				Resumed:      true,
				StartingStep: 5,
			},
		},
		{
			name: "BranchedRunRecord",
			run: &spb.RunRecord{
				Entity:    "test entity",
				Project:   "test project",
				RunId:     "test run ID",
				StartTime: timestamppb.New(startTime),
				BranchPoint: &spb.BranchPoint{
					Run:    "source run ID",
					Metric: "step",
					Value:  10,
				},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			x := setup(t)
			wandbFileWithRecords(t,
				x.TransactionLog,
				&spb.Record{RecordType: &spb.Record_Run{Run: tt.run}})

			runInfo, err := x.RunReader.ExtractRunInfo(context.Background())
			require.NoError(t, err)

			assert.Equal(t, &runsync.RunInfo{
				Entity:    "test entity",
				Project:   "test project",
				RunID:     "test run ID",
				StartTime: startTime,
			}, runInfo)
		})
	}
}

// TestProcessTransactionLog_ForwardsRecordsUnmodified proves the RunReader is
// format-agnostic: it must forward every record to the parser exactly as
// read from the log, whether the log predates offline resume (steps encoded
// as history items) or postdates it (no step items at all). Injecting a
// _step is HistoryStepTracker's job, downstream in the Sender -- see
// core/internal/stream/historystep_compat_test.go -- not the RunReader's.
func TestProcessTransactionLog_ForwardsRecordsUnmodified(t *testing.T) {
	tests := []struct {
		name    string
		history *spb.Record
	}{
		{
			name: "OldFormatHistoryRow",
			history: &spb.Record{
				Num: 1,
				RecordType: &spb.Record_History{History: &spb.HistoryRecord{
					Step: &spb.HistoryStep{Num: 0},
					Item: []*spb.HistoryItem{
						{NestedKey: []string{"loss"}, ValueJson: "0.5"},
						{NestedKey: []string{"_step"}, ValueJson: "0"},
					},
				}},
			},
		},
		{
			name: "NewFormatHistoryRow",
			history: &spb.Record{
				Num: 1,
				RecordType: &spb.Record_History{History: &spb.HistoryRecord{
					Item: []*spb.HistoryItem{
						{NestedKey: []string{"loss"}, ValueJson: "0.5"},
					},
				}},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			x := setup(t)
			wandbFileWithRecords(t, x.TransactionLog, tt.history, exitRecord(0))
			x.FakeRunWork.QueueResponse(&spb.ServerResponse{}) // for the exit record

			var forwarded *spb.Record
			gomock.InOrder(
				x.MockRecordParser.EXPECT().
					Parse(gomock.Any()).
					Do(func(r *spb.Record) { forwarded = r }).
					Return(&testWork{ID: 1}),
				x.MockRecordParser.EXPECT().
					Parse(isExitRecord(0)).
					Return(&testWork{ID: 2}),
			)

			err := x.RunReader.ProcessTransactionLog(context.Background())
			require.NoError(t, err)

			assert.Truef(t, proto.Equal(tt.history, forwarded),
				"RunReader must forward the record unmodified: got %v, want %v",
				forwarded, tt.history)
		})
	}
}

// TestExtract_ResumeModeSurvivesRoundTrip pins that RunRecord.resume_mode
// (proto field 24) round-trips through an actual transaction log write and
// read. This field is read and written independently by the Go core, the
// Python legacy sync path, and wandb-core's proto definitions; a field
// number mismatch between them would silently corrupt resume intent instead
// of failing loudly.
func TestExtract_ResumeModeSurvivesRoundTrip(t *testing.T) {
	x := setup(t)
	wandbFileWithRecords(t,
		x.TransactionLog,
		&spb.Record{
			Num: 1,
			RecordType: &spb.Record_Run{Run: &spb.RunRecord{
				Entity:     "test entity",
				Project:    "test project",
				RunId:      "test run ID",
				ResumeMode: true,
			}},
		},
		exitRecord(0))
	// The Run and Exit records require a response.
	x.FakeRunWork.QueueResponse(&spb.ServerResponse{})
	x.FakeRunWork.QueueResponse(&spb.ServerResponse{})

	var forwarded *spb.Record
	gomock.InOrder(
		x.MockRecordParser.EXPECT().
			Parse(isRecordWithNumber(1)).
			Do(func(r *spb.Record) { forwarded = r }).
			Return(&testWork{ID: 1}),
		x.MockRecordParser.EXPECT().
			Parse(isRunStartRequest()).
			Return(&testWork{ID: 2}),
		x.MockRecordParser.EXPECT().
			Parse(isExitRecord(0)).
			Return(&testWork{ID: 3}),
	)

	err := x.RunReader.ProcessTransactionLog(context.Background())
	require.NoError(t, err)

	require.NotNil(t, forwarded)
	assert.True(t, forwarded.GetRun().GetResumeMode())
}

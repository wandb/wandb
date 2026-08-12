package leet_test

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// TestLevelDBHistorySource_OldAndNewFormatLogsRenderSameXAxis pins R9: an old
// log (steps written twice, as HistoryRecord.Step and a "_step" item) and a
// new log for the same logical run (no step fields at all, since
// HistoryStepTracker now assigns _step downstream in the Sender rather than
// in the Handler) must render identically in `leet`, which is read-only and
// never runs HistoryStepTracker itself.
//
// This substitutes locally-written fixtures for the Phase 2 golden corpus
// (tests/assets/compat_logs/old_auto_steps and new_auto_steps), which this
// phase does not yet have; see TestLevelDBHistorySource_AssignsAutoStepForDisplay
// above for the established pattern this follows.
func TestLevelDBHistorySource_OldAndNewFormatLogsRenderSameXAxis(t *testing.T) {
	tests := []struct {
		name    string
		history []*spb.HistoryRecord
	}{
		{
			name: "OldFormat",
			history: []*spb.HistoryRecord{
				{
					Step: &spb.HistoryStep{Num: 0},
					Item: []*spb.HistoryItem{
						{NestedKey: []string{"loss"}, ValueJson: "0.1"},
						{NestedKey: []string{"_step"}, ValueJson: "0"},
					},
				},
				{
					Step: &spb.HistoryStep{Num: 1},
					Item: []*spb.HistoryItem{
						{NestedKey: []string{"loss"}, ValueJson: "0.2"},
						{NestedKey: []string{"_step"}, ValueJson: "1"},
					},
				},
				{
					Step: &spb.HistoryStep{Num: 2},
					Item: []*spb.HistoryItem{
						{NestedKey: []string{"loss"}, ValueJson: "0.3"},
						{NestedKey: []string{"_step"}, ValueJson: "2"},
					},
				},
			},
		},
		{
			name: "NewFormat",
			history: []*spb.HistoryRecord{
				{Item: []*spb.HistoryItem{{NestedKey: []string{"loss"}, ValueJson: "0.1"}}},
				{Item: []*spb.HistoryItem{{NestedKey: []string{"loss"}, ValueJson: "0.2"}}},
				{Item: []*spb.HistoryItem{{NestedKey: []string{"loss"}, ValueJson: "0.3"}}},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), tt.name+".wandb")

			w, err := transactionlog.OpenWriter(path)
			require.NoError(t, err)
			require.NoError(t, w.Write(&spb.Record{
				RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "run1"}},
			}))
			for _, h := range tt.history {
				require.NoError(t, w.Write(&spb.Record{
					RecordType: &spb.Record_History{History: h},
				}))
			}
			require.NoError(t, w.Write(&spb.Record{
				RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}},
			}))
			require.NoError(t, w.Close())

			s, err := leet.NewLevelDBHistorySource(path, observability.NewNoOpLogger())
			require.NoError(t, err)

			cmd := leet.ReadRecords(s, leet.BootLoadChunkSize, leet.BootLoadMaxTime)
			msg := cmd()
			batch, ok := msg.(leet.ChunkedBatchMsg)
			require.True(t, ok)

			var lastHistory leet.HistoryMsg
			for _, batchMsg := range batch.Msgs {
				if h, ok := batchMsg.(leet.HistoryMsg); ok {
					lastHistory = h
				}
			}
			require.Equal(t, []float64{0, 1, 2}, lastHistory.Metrics["loss"].X)
			require.Equal(t, []float64{0.1, 0.2, 0.3}, lastHistory.Metrics["loss"].Y)
		})
	}
}

package filestream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"

	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/sparselist"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestHistory_MergeAppends(t *testing.T) {
	req1 := &FileStreamRequest{HistoryLines: []string{"original"}}
	req2 := &FileStreamRequest{HistoryLines: []string{"new"}}

	req1.Merge(req2)

	assert.Equal(t, []string{"original", "new"}, req1.HistoryLines)
}

func TestEvents_MergeAppends(t *testing.T) {
	req1 := &FileStreamRequest{EventsLines: []string{"original"}}
	req2 := &FileStreamRequest{EventsLines: []string{"new"}}

	req1.Merge(req2)

	assert.Equal(t, []string{"original", "new"}, req1.EventsLines)
}

func TestSummary_MergeNil_NoChange(t *testing.T) {
	req1 := &FileStreamRequest{
		SummaryUpdates: runsummary.FromProto(&spb.SummaryRecord{
			Update: []*spb.SummaryItem{{Key: "xyz", ValueJson: `1`}},
		}),
	}
	req2 := &FileStreamRequest{}

	req1.Merge(req2)

	assert.NotNil(t, req1.SummaryUpdates)
}

func TestSummary_MergeNilAndNonNil_UsesLatest(t *testing.T) {
	req1 := &FileStreamRequest{}
	req2 := &FileStreamRequest{
		SummaryUpdates: runsummary.FromProto(&spb.SummaryRecord{
			Update: []*spb.SummaryItem{{Key: "xyz", ValueJson: `3`}},
		}),
	}

	req1.Merge(req2)

	assert.Equal(t, req2.SummaryUpdates, req1.SummaryUpdates)
}

func TestSummary_Merge_CombinesUpdates(t *testing.T) {
	req1 := &FileStreamRequest{
		SummaryUpdates: runsummary.FromProto(&spb.SummaryRecord{
			Update: []*spb.SummaryItem{{Key: "abc", ValueJson: `1`}},
		}),
	}
	req2 := &FileStreamRequest{
		SummaryUpdates: runsummary.FromProto(&spb.SummaryRecord{
			Update: []*spb.SummaryItem{{Key: "xyz", ValueJson: `2`}},
		}),
	}

	req1.Merge(req2)

	assert.Equal(t,
		runsummary.FromProto(&spb.SummaryRecord{
			Update: []*spb.SummaryItem{
				{Key: "abc", ValueJson: `1`},
				{Key: "xyz", ValueJson: `2`},
			},
		}),
		req1.SummaryUpdates)
}

func TestConsole_MergeUpdatesPreferringLast(t *testing.T) {
	req1 := &FileStreamRequest{ConsoleLines: &sparselist.SparseList[string]{}}
	req1.ConsoleLines.Put(0, "req1 - 0")
	req1.ConsoleLines.Put(5, "req1 - 5")
	req2 := &FileStreamRequest{ConsoleLines: &sparselist.SparseList[string]{}}
	req2.ConsoleLines.Put(0, "req2 - 0")
	req2.ConsoleLines.Put(6, "req2 - 6")

	req1.Merge(req2)

	assert.Equal(t,
		[]sparselist.Run[string]{
			{Start: 0, Items: []string{"req2 - 0"}},
			{Start: 5, Items: []string{"req1 - 5", "req2 - 6"}},
		},
		req1.ConsoleLines.ToRuns())
}

func TestUploadedFiles_MergeIsUnion(t *testing.T) {
	req1 := &FileStreamRequest{UploadedFiles: map[string]struct{}{
		"file1": {},
		"file2": {},
	}}
	req2 := &FileStreamRequest{UploadedFiles: map[string]struct{}{
		"file3": {},
	}}

	req1.Merge(req2)

	assert.Equal(t, map[string]struct{}{
		"file1": {},
		"file2": {},
		"file3": {},
	}, req1.UploadedFiles)
}

func TestExitCode_MergeTakesLatest(t *testing.T) {
	req1 := &FileStreamRequest{Complete: true, ExitCode: 111}
	req2 := &FileStreamRequest{Complete: true, ExitCode: 222}

	req1.Merge(req2)

	assert.True(t, req1.Complete)
	assert.EqualValues(t, 222, req1.ExitCode)
}

func TestExitCode_MergeIgnoresIfNotComplete(t *testing.T) {
	req1 := &FileStreamRequest{Complete: true, ExitCode: 111}
	req2 := &FileStreamRequest{Complete: false, ExitCode: 222}

	req1.Merge(req2)

	assert.True(t, req1.Complete)
	assert.EqualValues(t, 111, req1.ExitCode)
}

package filestream_test

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filestreamtest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// historyLinesFor replays a golden fixture's History records through
// HistoryUpdate.Apply, exactly as an *old* client's filestream uploader
// does today: HistoryUpdate.Apply only ever reads Record.Item, so it is
// unaffected by wandb PR #12110's format change and needs no update to
// stay a faithful stand-in for pre-PR code.
func historyLinesFor(t *testing.T, fixture string) []string {
	t.Helper()

	fs := filestreamtest.NewFakeFileStream()
	for _, record := range transactionlogtest.GoldenLogRecords(t, fixture) {
		history := record.GetHistory()
		if history == nil {
			continue
		}
		fs.StreamUpdate(&filestream.HistoryUpdate{Record: history})
	}

	req := fs.GetRequest(settings.New())
	return req.HistoryLines
}

func hasStepKey(t *testing.T, line string) bool {
	t.Helper()

	var decoded map[string]any
	require.NoError(t, json.Unmarshal([]byte(line), &decoded))
	_, ok := decoded["_step"]
	return ok
}

// TestHistoryUpdate_NewFormatLogHasNoStepAxis is the R7 format guard: it
// makes the on-disk format change visible without needing to ship an old
// binary, because the relevant old code is untouched by the PR --
// HistoryUpdate.Apply is absent from its diffstat.
//
// An old client reading a new-format log (new_auto_steps, whose auto-step
// rows carry no Record.Step or "_step" item -- see historystep.go and the
// golden corpus's goldenCorpus table) uploads history with no step axis at
// all; the old leet/UI would collapse every row to x=0. The same logical
// run written in the old format (old_auto_steps) does carry "_step" on
// every row. This test fails the day someone "fixes" the new format by
// putting "_step" back into HistoryRecord.Item, which is exactly the change
// we want surfaced rather than silently reverted.
func TestHistoryUpdate_NewFormatLogHasNoStepAxis(t *testing.T) {
	newLines := historyLinesFor(t, "new_auto_steps")
	require.NotEmpty(t, newLines)
	for i, line := range newLines {
		assert.False(t, hasStepKey(t, line),
			"new_auto_steps row %d: old code must not invent a step axis"+
				" that the new-format log doesn't carry: %s", i, line)
	}

	oldLines := historyLinesFor(t, "old_auto_steps")
	require.NotEmpty(t, oldLines)
	for i, line := range oldLines {
		assert.True(t, hasStepKey(t, line),
			"old_auto_steps row %d: the old format embeds \"_step\" in"+
				" every row and old code must still surface it: %s", i, line)
	}
}

// TestHistoryUpdate_IgnoresRecordStep is a narrower pin of the same fact:
// HistoryUpdate.Apply only ever reads Record.Item, never Record.Step, so a
// Record.Step with no accompanying "_step" item (the new explicit-step
// shape; see new_explicit_steps) still uploads with no step axis.
func TestHistoryUpdate_IgnoresRecordStep(t *testing.T) {
	fs := filestreamtest.NewFakeFileStream()
	fs.StreamUpdate(&filestream.HistoryUpdate{
		Record: &spb.HistoryRecord{
			Step: &spb.HistoryStep{Num: 5},
			Item: []*spb.HistoryItem{
				{NestedKey: []string{"x"}, ValueJson: "1"},
			},
		},
	})

	req := fs.GetRequest(settings.New())
	require.Len(t, req.HistoryLines, 1)
	assert.False(t, hasStepKey(t, req.HistoryLines[0]))
}

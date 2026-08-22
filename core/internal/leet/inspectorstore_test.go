package leet_test

import (
	"bytes"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// writeWandbFile writes the given records to a new .wandb file and returns
// its path.
func writeWandbFile(t *testing.T, records ...*spb.Record) string {
	t.Helper()

	path := filepath.Join(t.TempDir(), "run-test.wandb")
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	for _, record := range records {
		require.NoError(t, w.Write(record))
	}
	require.NoError(t, w.Close())

	return path
}

func inspectorTestRecords() []*spb.Record {
	return []*spb.Record{
		{RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{RunId: "abc123"},
		}},
		{RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{
				Step: &spb.HistoryStep{Num: 5},
				Item: []*spb.HistoryItem{{Key: "loss", ValueJson: "0.5"}},
			},
		}},
		{RecordType: &spb.Record_OutputRaw{
			OutputRaw: &spb.OutputRawRecord{Line: "\x1b[31mhello\x1b[0m world\n"},
		}},
		{RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_PartialHistory{
					PartialHistory: &spb.PartialHistoryRequest{},
				},
			},
		}},
		{RecordType: &spb.Record_Exit{
			Exit: &spb.RunExitRecord{ExitCode: 7},
		}},
	}
}

func TestInspectorStore_ScanAndRecordAt(t *testing.T) {
	path := writeWandbFile(t, inspectorTestRecords()...)

	store, err := leet.NewInspectorStore(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer store.Close()

	entries, atEOF, err := store.ScanBatch(100, time.Second)
	require.NoError(t, err)
	assert.True(t, atEOF)
	require.Len(t, entries, 5)

	assert.Equal(t, "run", entries[0].Type)
	assert.Equal(t, "abc123", entries[0].Summary)
	assert.Equal(t, "history", entries[1].Type)
	assert.Equal(t, "step 5", entries[1].Summary)
	assert.Equal(t, "output_raw", entries[2].Type)
	assert.Equal(t, "hello world", entries[2].Summary)
	assert.Equal(t, "request/partial_history", entries[3].Type)
	assert.Equal(t, "exit", entries[4].Type)
	assert.Equal(t, "code 7", entries[4].Summary)

	for i, e := range entries {
		assert.Equal(t, i+1, e.Num)
	}

	exitSeen, exitCode := store.ExitSeen()
	assert.True(t, exitSeen)
	assert.EqualValues(t, 7, exitCode)

	// Re-read records by offset, out of order.
	record, err := store.RecordAt(entries[1].Offset)
	require.NoError(t, err)
	assert.EqualValues(t, 5, record.GetHistory().GetStep().GetNum())

	record, err = store.RecordAt(entries[0].Offset)
	require.NoError(t, err)
	assert.Equal(t, "abc123", record.GetRun().GetRunId())
}

func TestInspectorStore_LiveAppend(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-live.wandb")
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	defer func() { _ = w.Close() }()

	require.NoError(t, w.Write(&spb.Record{
		RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "live"}},
	}))
	require.NoError(t, w.Flush())

	store, err := leet.NewInspectorStore(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer store.Close()

	entries, atEOF, err := store.ScanBatch(100, time.Second)
	require.NoError(t, err)
	assert.True(t, atEOF)
	require.Len(t, entries, 1)

	// Append while the store is at EOF; the next scan picks it up.
	require.NoError(t, w.Write(&spb.Record{
		RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{Step: &spb.HistoryStep{Num: 1}},
		},
	}))
	require.NoError(t, w.Flush())

	entries, atEOF, err = store.ScanBatch(100, time.Second)
	require.NoError(t, err)
	assert.True(t, atEOF)
	require.Len(t, entries, 1)
	assert.Equal(t, 2, entries[0].Num)
	assert.Equal(t, "history", entries[0].Type)
}

func TestDumpRecords(t *testing.T) {
	path := writeWandbFile(t, inspectorTestRecords()...)

	var buf bytes.Buffer
	require.NoError(t, leet.DumpRecords(path, &buf))

	out := buf.String()
	assert.Contains(t, out, "# record 1: run")
	assert.Contains(t, out, "# record 2: history")
	assert.Contains(t, out, "# record 5: exit")
	// prototext output whitespace is deliberately unstable; match loosely.
	assert.Regexp(t, `run_id:\s+"abc123"`, out)
	assert.Regexp(t, `exit_code:\s+7`, out)
}

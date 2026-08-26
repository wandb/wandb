package leet_test

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

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

func scanBatch(t *testing.T, store *leet.LiveStore, startNum int) leet.InspectorBatchMsg {
	t.Helper()
	msg := leet.ReadInspectorBatch(store, startNum)()
	require.IsType(t, leet.InspectorBatchMsg{}, msg)
	return msg.(leet.InspectorBatchMsg)
}

func TestReadInspectorBatch_ScanAndReadAt(t *testing.T) {
	path := writeWandbFile(t, inspectorTestRecords()...)
	logger := observability.NewNoOpLogger()

	scan, err := leet.NewLiveStore(path, logger)
	require.NoError(t, err)
	defer scan.Close()

	batch := scanBatch(t, scan, 1)
	assert.True(t, batch.AtEOF)
	require.Len(t, batch.Entries, 5)

	entries := batch.Entries
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

	assert.True(t, batch.ExitSeen)
	assert.EqualValues(t, 7, batch.ExitCode)
	assert.Zero(t, batch.Corrupt)

	// Re-read records by offset, out of order, with a separate reader.
	detail, err := leet.NewLiveStore(path, logger)
	require.NoError(t, err)
	defer detail.Close()

	record, err := detail.ReadAt(entries[1].Offset)
	require.NoError(t, err)
	assert.EqualValues(t, 5, record.GetHistory().GetStep().GetNum())

	record, err = detail.ReadAt(entries[0].Offset)
	require.NoError(t, err)
	assert.Equal(t, "abc123", record.GetRun().GetRunId())
}

func TestReadInspectorBatch_LiveAppend(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-live.wandb")
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	defer func() { _ = w.Close() }()

	require.NoError(t, w.Write(&spb.Record{
		RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "live"}},
	}))
	require.NoError(t, w.Flush())

	scan, err := leet.NewLiveStore(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer scan.Close()

	batch := scanBatch(t, scan, 1)
	assert.True(t, batch.AtEOF)
	require.Len(t, batch.Entries, 1)
	assert.False(t, batch.ExitSeen)

	// Append while the scan is at EOF; the next batch picks it up.
	require.NoError(t, w.Write(&spb.Record{
		RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{Step: &spb.HistoryStep{Num: 1}},
		},
	}))
	require.NoError(t, w.Flush())

	batch = scanBatch(t, scan, 2)
	assert.True(t, batch.AtEOF)
	require.Len(t, batch.Entries, 1)
	assert.Equal(t, 2, batch.Entries[0].Num)
	assert.Equal(t, "history", batch.Entries[0].Type)
}

func TestDumpRecords(t *testing.T) {
	path := writeWandbFile(t, inspectorTestRecords()...)

	var buf bytes.Buffer
	require.NoError(t, leet.DumpRecords(path, "", &buf))

	out := buf.String()
	assert.Contains(t, out, "# record 1: run")
	assert.Contains(t, out, "# record 2: history")
	assert.Contains(t, out, "# record 5: exit")
	// prototext output whitespace is deliberately unstable; match loosely.
	assert.Regexp(t, `run_id:\s+"abc123"`, out)
	assert.Regexp(t, `exit_code:\s+7`, out)
}

func TestDumpRecords_ResolvesLatestRun(t *testing.T) {
	wandbDir := t.TempDir()
	runDir := filepath.Join(wandbDir, "run-20260821_120000-abc123")
	require.NoError(t, os.MkdirAll(runDir, 0o755))

	w, err := transactionlog.OpenWriter(filepath.Join(runDir, "run-abc123.wandb"))
	require.NoError(t, err)
	require.NoError(t, w.Write(&spb.Record{
		RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "abc123"}},
	}))
	require.NoError(t, w.Close())
	require.NoError(t, os.Symlink(
		"run-20260821_120000-abc123", filepath.Join(wandbDir, "latest-run")))

	var buf bytes.Buffer
	require.NoError(t, leet.DumpRecords("", wandbDir, &buf))
	assert.Contains(t, buf.String(), "# record 1: run")
}

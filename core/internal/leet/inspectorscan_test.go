package leet_test

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	txnlogtest "github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

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
	path := txnlogtest.WandbFile(t, inspectorTestRecords()...)
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

func TestReadInspectorBatch_UnsupportedVersion(t *testing.T) {
	for _, test := range []struct {
		name    string
		version byte
	}{
		{name: "next version", version: 1},
		{name: "maximum version", version: 255},
	} {
		t.Run(test.name, func(t *testing.T) {
			path := writeUnsupportedWandbFile(t, test.version)
			scan, err := leet.NewLiveStore(path, observability.NewNoOpLogger())
			require.NoError(t, err)
			defer scan.Close()

			batch := scanBatch(t, scan, 1)
			assert.EqualError(t, batch.Err,
				"a newer wandb version is required to read this file")
			assert.Empty(t, batch.Entries)
			assert.Zero(t, batch.Corrupt)
			var versionErr *transactionlog.UnsupportedVersionError
			require.ErrorAs(t, batch.Err, &versionErr)
			assert.Equal(t, test.version, versionErr.Version)
		})
	}
}

func TestReadInspectorBatch_InvalidHeader(t *testing.T) {
	for _, test := range []struct {
		name    string
		header  []byte
		message string
	}{
		{
			name:    "identifier",
			header:  []byte("NOPE\xE1\xBE\x00"),
			message: "invalid W&B identifier",
		},
		{
			name:    "magic",
			header:  []byte(":W&B\x00\x00\x00"),
			message: "invalid W&B magic",
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "invalid.wandb")
			require.NoError(t, os.WriteFile(path, test.header, 0o600))
			scan, err := leet.NewLiveStore(path, observability.NewNoOpLogger())
			require.NoError(t, err)
			defer scan.Close()

			batch := scanBatch(t, scan, 1)
			assert.ErrorContains(t, batch.Err, test.message)
			assert.Empty(t, batch.Entries)
			assert.Zero(t, batch.Corrupt)
		})
	}
}

func TestReadInspectorBatch_SkipsCorruptRecord(t *testing.T) {
	path := writeWandbFile(t,
		&spb.Record{RecordType: &spb.Record_OutputRaw{
			OutputRaw: &spb.OutputRawRecord{Line: strings.Repeat("x", 32*1024)},
		}},
		&spb.Record{RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{Step: &spb.HistoryStep{Num: 5}},
		}},
	)
	data, err := os.ReadFile(path)
	require.NoError(t, err)
	// Corrupt the first chunk so recovery must skip to the next block.
	copy(data[7:], []byte{1, 2, 3, 4, 5, 6, 7})
	require.NoError(t, os.WriteFile(path, data, 0o600))

	scan, err := leet.NewLiveStore(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer scan.Close()

	batch := scanBatch(t, scan, 1)
	require.NoError(t, batch.Err)
	assert.True(t, batch.AtEOF)
	assert.Equal(t, 1, batch.Corrupt)
	require.Len(t, batch.Entries, 1)
	assert.Equal(t, "history", batch.Entries[0].Type)
	assert.Equal(t, "step 5", batch.Entries[0].Summary)
}

func TestReadInspectorBatch_PartialRecordResumesAfterAppend(t *testing.T) {
	path := writeWandbFile(t, inspectorTestRecords()...)
	data, err := os.ReadFile(path)
	require.NoError(t, err)
	require.NoError(t, os.Truncate(path, int64(len(data)-1)))
	scan, err := leet.NewLiveStore(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer scan.Close()

	batch := scanBatch(t, scan, 1)
	require.NoError(t, batch.Err)
	assert.True(t, batch.AtEOF)
	assert.Zero(t, batch.Corrupt)
	assert.False(t, batch.ExitSeen)
	require.Len(t, batch.Entries, 4)

	f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0)
	require.NoError(t, err)
	_, err = f.Write(data[len(data)-1:])
	require.NoError(t, err)
	require.NoError(t, f.Close())

	batch = scanBatch(t, scan, 5)
	require.NoError(t, batch.Err)
	assert.True(t, batch.AtEOF)
	assert.Zero(t, batch.Corrupt)
	assert.True(t, batch.ExitSeen)
	require.Len(t, batch.Entries, 1)
	assert.Equal(t, "exit", batch.Entries[0].Type)
	assert.Equal(t, 5, batch.Entries[0].Num)
}

func TestDumpRecords(t *testing.T) {
	path := txnlogtest.WandbFile(t, inspectorTestRecords()...)

	var buf bytes.Buffer
	require.NoError(t, leet.DumpRecords(path, "", &buf, &buf, leet.DumpOptions{}))

	out := buf.String()
	assert.Contains(t, out, "# record 1: run")
	assert.Contains(t, out, "# record 2: history")
	assert.Contains(t, out, "# record 5: exit")
	// prototext output whitespace is deliberately unstable; match loosely.
	assert.Regexp(t, `run_id:\s+"abc123"`, out)
	assert.Regexp(t, `exit_code:\s+7`, out)
}

func TestDumpRecords_NotATransactionLog(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-text.wandb")
	require.NoError(t, os.WriteFile(path, []byte("not a transaction log\n"), 0o644))

	var buf bytes.Buffer
	assert.Error(t, leet.DumpRecords(path, "", &buf, &buf, leet.DumpOptions{}))
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
	require.NoError(t, leet.DumpRecords("", wandbDir, &buf, &buf, leet.DumpOptions{}))
	assert.Contains(t, buf.String(), "# record 1: run")
}

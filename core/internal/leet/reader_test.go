package leet_test

import (
	"fmt"
	"io"
	"path/filepath"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// Verifies the missing-file path in NewWandbReader. reader.go
// returns a descriptive error when the file doesn't exist.
func TestNewWandbReader_MissingFile(t *testing.T) {
	_, err := leet.NewWandbReader("no/such/file.wandb", observability.NewNoOpLogger())
	require.Error(t, err)
}

func TestParseHistory_StepAndMetrics(t *testing.T) {
	h := &spb.HistoryRecord{Item: []*spb.HistoryItem{
		{NestedKey: []string{"_step"}, ValueJson: "2"},
		{NestedKey: []string{"loss"}, ValueJson: "0.5"},
		{NestedKey: []string{"_runtime"}, ValueJson: "1.2"},
	}}
	msg := leet.ParseHistory(h).(leet.HistoryMsg)
	require.Equal(t, 2, msg.Step)
	require.Equal(t, 0.5, msg.Metrics["loss"])
}

func TestReadAllRecordsChunked_HistoryThenExit(t *testing.T) {
	path := filepath.Join(t.TempDir(), "chunky.wandb")

	// Write a valid header + two records (history, exit).
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	h := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"_step"}, ValueJson: "1"},
			{NestedKey: []string{"loss"}, ValueJson: "0.42"},
		},
	}
	err = w.Write(&spb.Record{RecordType: &spb.Record_History{History: h}})
	require.NoError(t, err)
	err = w.Write(&spb.Record{RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}}})
	require.NoError(t, err)
	_ = w.Close()

	r, err := leet.NewWandbReader(path, observability.NewNoOpLogger())
	require.NoError(t, err)

	cmd := leet.ReadAllRecordsChunked(r)
	msg := cmd()
	batch, ok := msg.(leet.ChunkedBatchMsg)
	require.True(t, ok)
	require.False(t, batch.HasMore)
	require.NotEqual(t, 0, batch.Progress)
	require.NotEqual(t, 0, batch.Msgs)

	var sawHistory, sawComplete bool
	for _, m := range batch.Msgs {
		switch mm := m.(type) {
		case leet.HistoryMsg:
			sawHistory = true
			require.Equal(t, 1, mm.Step)
			require.Equal(t, 0.42, mm.Metrics["loss"])
		case leet.FileCompleteMsg:
			sawComplete = true
			require.Equal(t, int32(0), mm.ExitCode)
		}
	}
	require.True(t, sawHistory, "expected to see history message")
	require.True(t, sawComplete, "expected to see file-complete message")
}

//gocyclo:ignore
func TestReadNext_MultipleRecordTypes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "readnext.wandb")

	// Write valid header and various record types
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)

	// Write different record types
	records := []struct {
		name   string
		record *spb.Record
	}{
		{
			name: "run",
			record: &spb.Record{
				RecordType: &spb.Record_Run{
					Run: &spb.RunRecord{
						RunId:       "test-run-123",
						DisplayName: "Test Run",
						Project:     "test-project",
					},
				},
			},
		},
		{
			name: "stats",
			record: &spb.Record{
				RecordType: &spb.Record_Stats{
					Stats: &spb.StatsRecord{
						Timestamp: &timestamppb.Timestamp{Seconds: time.Now().Unix()},
						Item: []*spb.StatsItem{
							{Key: "cpu", ValueJson: "45.5"},
							{Key: "memory_percent", ValueJson: "78.2"},
						},
					},
				},
			},
		},
		{
			name: "summary",
			record: &spb.Record{
				RecordType: &spb.Record_Summary{
					Summary: &spb.SummaryRecord{
						Update: []*spb.SummaryItem{
							{
								NestedKey: []string{"best_loss"},
								ValueJson: "0.123",
							},
						},
					},
				},
			},
		},
		{
			name: "environment",
			record: &spb.Record{
				RecordType: &spb.Record_Environment{
					Environment: &spb.EnvironmentRecord{
						WriterId: "writer-1",
						Python:   "3.9.7",
						Os:       "Linux",
					},
				},
			},
		},
		{
			name: "exit",
			record: &spb.Record{
				RecordType: &spb.Record_Exit{
					Exit: &spb.RunExitRecord{
						ExitCode: 0,
					},
				},
			},
		},
	}

	for _, rec := range records {
		require.NoError(t, w.Write(rec.record), "write %s", rec.name)
	}
	w.Close()

	// Read back using ReadNext
	reader, err := leet.NewWandbReader(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer reader.Close()

	// Test ReadNext for each record type
	tests := []struct {
		name     string
		validate func(tea.Msg)
	}{
		{
			name: "run",
			validate: func(msg tea.Msg) {
				runMsg, ok := msg.(leet.RunMsg)
				require.True(t, ok, "expected RunMsg, got %T", msg)
				require.Equal(t, "test-run-123", runMsg.ID)
				require.Equal(t, "Test Run", runMsg.DisplayName)
				require.Equal(t, "test-project", runMsg.Project)
			},
		},
		{
			name: "stats",
			validate: func(msg tea.Msg) {
				statsMsg, ok := msg.(leet.StatsMsg)
				require.True(t, ok, "expected StatsMsg, got %T", msg)
				require.Equal(t, 45.5, statsMsg.Metrics["cpu"])
				require.Equal(t, 78.2, statsMsg.Metrics["memory_percent"])
			},
		},
		{
			name: "summary",
			validate: func(msg tea.Msg) {
				summaryMsg, ok := msg.(leet.SummaryMsg)
				require.True(t, ok, "expected SummaryMsg, got %T", msg)
				require.NotNil(t, summaryMsg.Summary)
				require.Len(t, summaryMsg.Summary.Update, 1)
			},
		},
		{
			name: "environment",
			validate: func(msg tea.Msg) {
				envMsg, ok := msg.(leet.SystemInfoMsg)
				require.True(t, ok, "expected SystemInfoMsg, got %T", msg)
				require.Equal(t, "writer-1", envMsg.Record.WriterId)
				require.Equal(t, "3.9.7", envMsg.Record.Python)
			},
		},
		{
			name: "exit",
			validate: func(msg tea.Msg) {
				exitMsg, ok := msg.(leet.FileCompleteMsg)
				require.True(t, ok, "expected FileCompleteMsg, got %T", msg)
				require.Equal(t, int32(0), exitMsg.ExitCode)
			},
		},
	}

	for _, tt := range tests {
		msg, err := reader.ReadNext()
		require.NoError(t, err, "%s: ReadNext error", tt.name)
		require.NotNil(t, msg, "%s: ReadNext returned nil message", tt.name)
		tt.validate(msg)
	}

	// After exit record, should get EOF
	_, err = reader.ReadNext()
	require.ErrorIs(t, err, io.EOF)
}

func TestParseStats_ComplexMetrics(t *testing.T) {
	stats := &spb.StatsRecord{
		Timestamp: &timestamppb.Timestamp{Seconds: 1234567890},
		Item: []*spb.StatsItem{
			{Key: "cpu", ValueJson: "42.5"},
			{Key: "memory_percent", ValueJson: "85.3"},
			{Key: "gpu.0.temp", ValueJson: "75"},
			{Key: "invalid", ValueJson: "not_a_number"},
			{Key: "disk.used", ValueJson: "\"123.45\""}, // Quoted number
			{Key: "", ValueJson: "100"},                 // Empty key
		},
	}

	msg := leet.ParseStats(stats).(leet.StatsMsg)

	// Verify timestamp
	require.Equal(t, int64(1234567890), msg.Timestamp)

	// Verify valid metrics were parsed
	expectedMetrics := map[string]float64{
		"cpu":            42.5,
		"memory_percent": 85.3,
		"gpu.0.temp":     75,
		"disk.used":      123.45,
	}

	for key, expectedValue := range expectedMetrics {
		require.Contains(t, msg.Metrics, key)
		require.Equal(t, expectedValue, msg.Metrics[key])
	}

	// Verify invalid metrics were skipped
	require.NotContains(t, msg.Metrics, "invalid")
}

func TestReadAvailableRecords_BatchProcessing(t *testing.T) {
	path := filepath.Join(t.TempDir(), "batch.wandb")

	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)

	// Write many history records
	const numRecords = 100
	for i := range numRecords {
		h := &spb.HistoryRecord{
			Item: []*spb.HistoryItem{
				{NestedKey: []string{"_step"}, ValueJson: fmt.Sprintf("%d", i)},
				{NestedKey: []string{"loss"}, ValueJson: fmt.Sprintf("%f", float64(i)*0.1)},
			},
		}
		require.NoError(t, w.Write(&spb.Record{RecordType: &spb.Record_History{History: h}}), "write history %d", i)
	}
	w.Close()

	reader, err := leet.NewWandbReader(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer reader.Close()

	// Test ReadAvailableRecords batching
	cmd := leet.ReadAvailableRecords(reader)
	msg := cmd()

	batchMsg, ok := msg.(leet.BatchedRecordsMsg)
	require.True(t, ok, "expected BatchedRecordsMsg, got %T", msg)

	// Should have read multiple records in batch
	require.NotEmpty(t, batchMsg.Msgs)

	// Verify first few messages
	for i, subMsg := range batchMsg.Msgs {
		if i >= 3 {
			break // Just check first few
		}
		histMsg, ok := subMsg.(leet.HistoryMsg)
		require.True(t, ok, "msg %d: expected HistoryMsg, got %T", i, subMsg)
		require.Equal(t, i, histMsg.Step, "msg %d", i)
	}

	// Test reading when no more data available
	// First consume all remaining data
	for {
		cmd = leet.ReadAvailableRecords(reader)
		msg = cmd()
		if msg == nil {
			break // No more data
		}
	}

	// Now verify returns nil when no data
	cmd = leet.ReadAvailableRecords(reader)
	msg = cmd()
	require.Nil(t, msg)
}

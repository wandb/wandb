package leet_test

import (
	"fmt"
	"io"
	"os"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// Verifies the missing-file path in NewWandbReader. reader.go
// returns a descriptive error when the file doesn't exist.
func TestNewWandbReader_MissingFile(t *testing.T) {
	if _, err := leet.NewWandbReader("no/such/file.wandb"); err == nil {
		t.Fatalf("expected error for missing .wandb file, got nil")
	}
}

func TestParseHistory_StepAndMetrics(t *testing.T) {
	t.Parallel()
	h := &spb.HistoryRecord{Item: []*spb.HistoryItem{
		{NestedKey: []string{"_step"}, ValueJson: "2"},
		{NestedKey: []string{"loss"}, ValueJson: "0.5"},
		{NestedKey: []string{"_runtime"}, ValueJson: "1.2"},
	}}
	msg := leet.ParseHistory(h).(leet.HistoryMsg)
	if msg.Step != 2 {
		t.Fatalf("step=%d", msg.Step)
	}
	if got := msg.Metrics["loss"]; got != 0.5 {
		t.Fatalf("loss=%v", got)
	}
}

func TestReadAllRecordsChunked_HistoryThenExit(t *testing.T) {
	tmp, err := os.CreateTemp(t.TempDir(), "chunk-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	_ = tmp.Close()

	// Write a valid header + two records (history, exit).
	st := stream.NewStore(tmp.Name())
	if err := st.Open(os.O_WRONLY); err != nil {
		t.Fatalf("open store: %v", err)
	}
	h := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"_step"}, ValueJson: "1"},
			{NestedKey: []string{"loss"}, ValueJson: "0.42"},
		},
	}
	if err := st.Write(&spb.Record{RecordType: &spb.Record_History{History: h}}); err != nil {
		t.Fatalf("write history: %v", err)
	}
	if err := st.Write(&spb.Record{RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}}}); err != nil {
		t.Fatalf("write exit: %v", err)
	}
	_ = st.Close()

	r, err := leet.NewWandbReader(tmp.Name())
	if err != nil {
		t.Fatalf("NewWandbReader: %v", err)
	}

	cmd := leet.ReadAllRecordsChunked(r)
	msg := cmd()
	batch, ok := msg.(leet.ChunkedBatchMsg)
	if !ok {
		t.Fatalf("got %T; want ChunkedBatchMsg", msg)
	}
	if batch.HasMore {
		t.Fatal("HasMore=true; want false (exit encountered)")
	}
	if batch.Progress == 0 || len(batch.Msgs) == 0 {
		t.Fatalf("empty batch: %+v", batch)
	}

	var sawHistory, sawComplete bool
	for _, m := range batch.Msgs {
		switch mm := m.(type) {
		case leet.HistoryMsg:
			sawHistory = true
			if mm.Step != 1 {
				t.Fatalf("history step=%d; want 1", mm.Step)
			}
			if got := mm.Metrics["loss"]; got != 0.42 {
				t.Fatalf("loss=%v; want 0.42", got)
			}
		case leet.FileCompleteMsg:
			sawComplete = true
			if mm.ExitCode != 0 {
				t.Fatalf("exit code=%d; want 0", mm.ExitCode)
			}
		}
	}
	if !sawHistory || !sawComplete {
		t.Fatalf("expected history+file-complete; got history=%v complete=%v", sawHistory, sawComplete)
	}
}

func TestReadNext_MultipleRecordTypes(t *testing.T) {
	tmp, err := os.CreateTemp(t.TempDir(), "readnext-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	defer tmp.Close()

	// Write valid header and various record types
	st := stream.NewStore(tmp.Name())
	if err := st.Open(os.O_WRONLY); err != nil {
		t.Fatalf("open store: %v", err)
	}

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
		if err := st.Write(rec.record); err != nil {
			t.Fatalf("write %s: %v", rec.name, err)
		}
	}
	st.Close()

	// Read back using ReadNext
	reader, err := leet.NewWandbReader(tmp.Name())
	if err != nil {
		t.Fatalf("NewWandbReader: %v", err)
	}
	defer reader.Close()

	// Test ReadNext for each record type
	tests := []struct {
		name     string
		validate func(tea.Msg) error
	}{
		{
			name: "run",
			validate: func(msg tea.Msg) error {
				runMsg, ok := msg.(leet.RunMsg)
				if !ok {
					return errorf("expected RunMsg, got %T", msg)
				}
				if runMsg.ID != "test-run-123" {
					return errorf("ID=%s, want test-run-123", runMsg.ID)
				}
				if runMsg.DisplayName != "Test Run" {
					return errorf("DisplayName=%s, want Test Run", runMsg.DisplayName)
				}
				if runMsg.Project != "test-project" {
					return errorf("Project=%s, want test-project", runMsg.Project)
				}
				return nil
			},
		},
		{
			name: "stats",
			validate: func(msg tea.Msg) error {
				statsMsg, ok := msg.(leet.StatsMsg)
				if !ok {
					return errorf("expected StatsMsg, got %T", msg)
				}
				if statsMsg.Metrics["cpu"] != 45.5 {
					return errorf("cpu=%v, want 45.5", statsMsg.Metrics["cpu"])
				}
				if statsMsg.Metrics["memory_percent"] != 78.2 {
					return errorf("memory_percent=%v, want 78.2", statsMsg.Metrics["memory_percent"])
				}
				return nil
			},
		},
		{
			name: "summary",
			validate: func(msg tea.Msg) error {
				summaryMsg, ok := msg.(leet.SummaryMsg)
				if !ok {
					return errorf("expected SummaryMsg, got %T", msg)
				}
				if summaryMsg.Summary == nil {
					return errorf("Summary is nil")
				}
				if len(summaryMsg.Summary.Update) != 1 {
					return errorf("Update length=%d, want 1", len(summaryMsg.Summary.Update))
				}
				return nil
			},
		},
		{
			name: "environment",
			validate: func(msg tea.Msg) error {
				envMsg, ok := msg.(leet.SystemInfoMsg)
				if !ok {
					return errorf("expected SystemInfoMsg, got %T", msg)
				}
				if envMsg.Record.WriterId != "writer-1" {
					return errorf("WriterId=%s, want writer-1", envMsg.Record.WriterId)
				}
				if envMsg.Record.Python != "3.9.7" {
					return errorf("Python=%s, want 3.9.7", envMsg.Record.Python)
				}
				return nil
			},
		},
		{
			name: "exit",
			validate: func(msg tea.Msg) error {
				exitMsg, ok := msg.(leet.FileCompleteMsg)
				if !ok {
					return errorf("expected FileCompleteMsg, got %T", msg)
				}
				if exitMsg.ExitCode != 0 {
					return errorf("ExitCode=%d, want 0", exitMsg.ExitCode)
				}
				return nil
			},
		},
	}

	for _, tt := range tests {
		msg, err := reader.ReadNext()
		if err != nil && err != io.EOF {
			t.Fatalf("%s: ReadNext error: %v", tt.name, err)
		}
		if msg == nil {
			t.Fatalf("%s: ReadNext returned nil message", tt.name)
		}
		if err := tt.validate(msg); err != nil {
			t.Fatalf("%s: %v", tt.name, err)
		}
	}

	// After exit record, should get EOF
	_, err = reader.ReadNext()
	if err != io.EOF {
		t.Fatalf("expected EOF after exit record, got %v", err)
	}
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
	if msg.Timestamp != 1234567890 {
		t.Fatalf("Timestamp=%d, want 1234567890", msg.Timestamp)
	}

	// Verify valid metrics were parsed
	expectedMetrics := map[string]float64{
		"cpu":            42.5,
		"memory_percent": 85.3,
		"gpu.0.temp":     75,
		"disk.used":      123.45,
	}

	for key, expectedValue := range expectedMetrics {
		if value, ok := msg.Metrics[key]; !ok {
			t.Errorf("missing metric %s", key)
		} else if value != expectedValue {
			t.Errorf("metric %s=%v, want %v", key, value, expectedValue)
		}
	}

	// Verify invalid metrics were skipped
	if _, ok := msg.Metrics["invalid"]; ok {
		t.Error("invalid metric should not be parsed")
	}
}

func TestReadAvailableRecords_BatchProcessing(t *testing.T) {
	tmp, err := os.CreateTemp(t.TempDir(), "batch-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	defer tmp.Close()

	st := stream.NewStore(tmp.Name())
	if err := st.Open(os.O_WRONLY); err != nil {
		t.Fatalf("open store: %v", err)
	}

	// Write many history records
	const numRecords = 100
	for i := range numRecords {
		h := &spb.HistoryRecord{
			Item: []*spb.HistoryItem{
				{NestedKey: []string{"_step"}, ValueJson: fmt.Sprintf("%d", i)},
				{NestedKey: []string{"loss"}, ValueJson: fmt.Sprintf("%f", float64(i)*0.1)},
			},
		}
		if err := st.Write(&spb.Record{RecordType: &spb.Record_History{History: h}}); err != nil {
			t.Fatalf("write history %d: %v", i, err)
		}
	}
	st.Close()

	reader, err := leet.NewWandbReader(tmp.Name())
	if err != nil {
		t.Fatalf("NewWandbReader: %v", err)
	}
	defer reader.Close()

	// Test ReadAvailableRecords batching
	cmd := leet.ReadAvailableRecords(reader)
	msg := cmd()

	batchMsg, ok := msg.(leet.BatchedRecordsMsg)
	if !ok {
		t.Fatalf("expected BatchedRecordsMsg, got %T", msg)
	}

	// Should have read multiple records in batch
	if len(batchMsg.Msgs) == 0 {
		t.Fatal("batch should contain messages")
	}

	// Verify first few messages
	for i, subMsg := range batchMsg.Msgs {
		if i >= 3 {
			break // Just check first few
		}
		histMsg, ok := subMsg.(leet.HistoryMsg)
		if !ok {
			t.Fatalf("msg %d: expected HistoryMsg, got %T", i, subMsg)
		}
		if histMsg.Step != i {
			t.Errorf("msg %d: Step=%d, want %d", i, histMsg.Step, i)
		}
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
	if msg != nil {
		t.Fatalf("expected nil when no data available, got %T", msg)
	}
}

// Helper functions
func errorf(format string, args ...any) error {
	return &testError{msg: format, args: args}
}

type testError struct {
	msg  string
	args []any
}

func (e *testError) Error() string {
	if len(e.args) > 0 {
		return fmt.Sprintf(e.msg, e.args...)
	}
	return e.msg
}

package leet_test

import (
	"os"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Verifies the missing-file path in NewWandbReader. reader.go
// returns a descriptive error when the file doesn't exist.
func TestNewWandbReader_MissingFile(t *testing.T) {
	t.Parallel()
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
	t.Parallel()

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
		default:
			_ = m.(tea.Msg) // keep interface assertions honest
		}
	}
	if !sawHistory || !sawComplete {
		t.Fatalf("expected history+file-complete; got history=%v complete=%v", sawHistory, sawComplete)
	}
}

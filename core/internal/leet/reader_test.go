package leet_test

import (
	"os"
	"testing"

	"github.com/wandb/wandb/core/internal/leet"
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

// Ensures LiveStore.Close is idempotent, and that an empty temp file
// is acceptable to NewLiveStore (header verify allows io.EOF).
func TestLiveStore_Close_Idempotent(t *testing.T) {
	t.Parallel()

	tmp, err := os.CreateTemp(t.TempDir(), "empty-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	_ = tmp.Close()

	ls, err := leet.NewLiveStore(tmp.Name())
	if err != nil {
		t.Fatalf("NewLiveStore(empty) = %v; want nil", err)
	}

	if err := ls.Close(); err != nil {
		t.Fatalf("first Close() = %v; want nil", err)
	}
	if err := ls.Close(); err != nil {
		t.Fatalf("second Close() = %v; want nil", err)
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

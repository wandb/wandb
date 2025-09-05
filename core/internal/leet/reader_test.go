package leet_test

import (
	"os"
	"testing"

	"github.com/wandb/wandb/core/internal/leet"
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

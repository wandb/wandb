package runfiles

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestFileCleaner(t *testing.T) {
	// Create a temporary directory for test files
	tmpDir := t.TempDir()
	logger := observability.NewNoOpLogger()

	t.Run("basic file deletion", func(t *testing.T) {
		// Create a test file
		testFile := filepath.Join(tmpDir, "test.txt")
		err := os.WriteFile(testFile, []byte("test content"), 0644)
		assert.NoError(t, err)

		// Create and start file cleaner
		cleaner := NewFileCleaner(logger)

		// Queue file for deletion
		cleaner.ScheduleDeleteFile(testFile)

		// Wait up to 5 seconds for deletion to complete
		deadline := time.Now().Add(5 * time.Second)
		for time.Now().Before(deadline) {
			if _, err := os.Stat(testFile); os.IsNotExist(err) {
				// File was deleted successfully
				return
			}
			time.Sleep(10 * time.Millisecond)
		}
		t.Fatal("file was not deleted.")
	})

	t.Run("non-existent file handling", func(t *testing.T) {
		cleaner := NewFileCleaner(logger)

		nonExistentFile := filepath.Join(tmpDir, "nonexistent.txt")
		cleaner.ScheduleDeleteFile(nonExistentFile)

		_, err := os.Stat(nonExistentFile)
		assert.True(t, os.IsNotExist(err))
	})
}

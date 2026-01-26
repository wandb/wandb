package runconsolelogs_test

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/paths"
	. "github.com/wandb/wandb/core/internal/runconsolelogs"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Helper to verify chunk files exist and return their paths.
func getChunkFiles(t *testing.T, tmpDir string) []string {
	t.Helper()

	files, err := filepath.Glob(filepath.Join(tmpDir, "logs", "*.log"))
	require.NoError(t, err)
	t.Logf("Found chunk files: %v", files)

	sort.Strings(files) // Sort for consistent ordering
	return files
}

// waitToDebounce waits enough time for the debouncing mechanism to flush.
//
// Must be called inside synctest.Test().
func waitToDebounce(t *testing.T) {
	t.Helper()
	time.Sleep(5 * time.Second)
	synctest.Wait()
}

// FakeUploader implements the Uploader interface.
//
// The outputFileWriter only calls the UploadNow method of its uploader
// on output file rotation and on finish, so we only need to verify that
// the UploadNow method was called.
type FakeUploader struct {
	uploadedPaths []paths.RelativePath
}

func NewFakeUploader() *FakeUploader {
	return &FakeUploader{
		uploadedPaths: make([]paths.RelativePath, 0),
	}
}

func (f *FakeUploader) Process(record *spb.FilesRecord) {}

func (f *FakeUploader) UploadNow(path paths.RelativePath, category filetransfer.RunFileKind) {
	f.uploadedPaths = append(f.uploadedPaths, path)
}
func (f *FakeUploader) UploadAtEnd(path paths.RelativePath, category filetransfer.RunFileKind) {}

func (f *FakeUploader) UploadRemaining() {}

func (f *FakeUploader) Finish() {}

// TestOutputFileWriterRotationBySize verifies that chunks rotate based on size.
func TestOutputFileWriterRotationBySize(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		tmpDir := t.TempDir()
		uploader := NewFakeUploader()

		writer := NewOutputFileWriter(OutputFileWriterParams{
			Multipart:     true,
			MaxChunkBytes: 100,

			FilesDir:       tmpDir,
			OutputFileName: "output.log",
			Logger:         observabilitytest.NewTestLogger(t),
			UploaderOrNil:  uploader,
		})

		// Write first batch - should fit in one chunk.
		writer.UpdateLine(0, RunLogsLineForTest(strings.Repeat("a", 30)))
		writer.UpdateLine(1, RunLogsLineForTest(strings.Repeat("b", 30)))
		waitToDebounce(t)

		// Write second batch - should trigger rotation (total > 100 bytes).
		writer.UpdateLine(2, RunLogsLineForTest(strings.Repeat("c", 30)))
		writer.UpdateLine(3, RunLogsLineForTest(strings.Repeat("d", 30)))
		waitToDebounce(t)

		// First chunk should have been uploaded during rotation.
		assert.Len(t, uploader.uploadedPaths, 1)

		// Write more data to create the second chunk file.
		writer.UpdateLine(4, RunLogsLineForTest("e"))
		synctest.Wait()

		writer.Finish()

		// Should have created and uploaded 2 chunk files.
		assert.Len(t, getChunkFiles(t, tmpDir), 2)
		assert.Len(t, uploader.uploadedPaths, 2)
	})
}

// TestOutputFileWriterRotationByTime verifies that chunks rotate based on time.
func TestOutputFileWriterRotationByTime(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		tmpDir := t.TempDir()
		uploader := NewFakeUploader()

		writer := NewOutputFileWriter(OutputFileWriterParams{
			Multipart:        true,
			MaxChunkDuration: 5 * time.Minute,

			FilesDir:       tmpDir,
			OutputFileName: "output.log",
			Logger:         observabilitytest.NewTestLogger(t),
			UploaderOrNil:  uploader,
		})

		// Write initial line.
		writer.UpdateLine(0, RunLogsLineForTest("first batch"))
		waitToDebounce(t)

		// Wait for the chunking threshold.
		time.Sleep(5 * time.Minute)

		// Write more lines - should trigger time-based rotation.
		writer.UpdateLine(1, RunLogsLineForTest("second batch"))
		waitToDebounce(t)

		// First chunk should have been uploaded.
		assert.Len(t, uploader.uploadedPaths, 1)

		// Write data to ensure second chunk file is created.
		writer.UpdateLine(2, RunLogsLineForTest("more data"))
		waitToDebounce(t)

		writer.Finish()

		// Should have created and uploaded 2 chunk files.
		assert.Len(t, getChunkFiles(t, tmpDir), 2)
		assert.Len(t, uploader.uploadedPaths, 2)
	})
}

// TestOutputFileWriterNoRotation verifies behavior when no rotation occurs.
func TestOutputFileWriterNoRotation(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		tmpDir := t.TempDir()
		uploader := NewFakeUploader()

		writer := NewOutputFileWriter(OutputFileWriterParams{
			Multipart:     true,
			MaxChunkBytes: 10000, // Large size to prevent rotation.

			FilesDir:       tmpDir,
			OutputFileName: "output.log",

			Logger:        observabilitytest.NewTestLogger(t),
			UploaderOrNil: uploader,
		})

		// Write some data.
		writer.UpdateLine(0, RunLogsLineForTest("line 1"))
		writer.UpdateLine(1, RunLogsLineForTest("line 2"))
		writer.UpdateLine(2, RunLogsLineForTest("line 3"))
		waitToDebounce(t)

		// No uploads yet (no rotation occurred).
		assert.Len(t, uploader.uploadedPaths, 0)

		writer.Finish()

		// Should have created and uploaded 1 chunk file.
		assert.Len(t, getChunkFiles(t, tmpDir), 1)
		assert.Len(t, uploader.uploadedPaths, 1)
	})
}

// TestOutputFileWriterNoData verifies behavior when no data is written.
func TestOutputFileWriterNoData(t *testing.T) {
	tmpDir := t.TempDir()
	uploader := NewFakeUploader()

	writer := NewOutputFileWriter(OutputFileWriterParams{
		Multipart:     true,
		MaxChunkBytes: 100,

		FilesDir:       tmpDir,
		OutputFileName: "output.log",
		UploaderOrNil:  uploader,
	})

	// Finish without writing any data.
	writer.Finish()

	// No files should be created.
	assert.Empty(t, getChunkFiles(t, tmpDir))
	assert.Empty(t, uploader.uploadedPaths)
}

// TestOutputFileWriterCrossChunkLineModification verifies that attempting
// to modify a line from a previous chunk after rotation is handled correctly.
func TestOutputFileWriterCrossChunkLineModification(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		tmpDir := t.TempDir()
		uploader := NewFakeUploader()

		writer := NewOutputFileWriter(OutputFileWriterParams{
			Multipart:     true,
			MaxChunkBytes: 100,

			FilesDir:       tmpDir,
			OutputFileName: "output.log",
			Logger:         observabilitytest.NewTestLogger(t),
			UploaderOrNil:  uploader,
		})

		// Write lines 0-3 (triggers rotation at ~120 bytes).
		writer.UpdateLine(0, RunLogsLineForTest(strings.Repeat("a", 30)))
		writer.UpdateLine(1, RunLogsLineForTest(strings.Repeat("b", 30)))
		writer.UpdateLine(2, RunLogsLineForTest(strings.Repeat("c", 30)))
		writer.UpdateLine(3, RunLogsLineForTest(strings.Repeat("d", 30)))
		waitToDebounce(t)

		// First chunk should be rotated.
		assert.Len(t, uploader.uploadedPaths, 1)

		// Try to modify line 1 from the previous chunk - should be silently ignored.
		writer.UpdateLine(1, RunLogsLineForTest("modified line 1"))
		writer.UpdateLine(4, RunLogsLineForTest("new line 4"))
		waitToDebounce(t)

		writer.Finish()

		// Should have 2 chunks total.
		chunkFiles := getChunkFiles(t, tmpDir)
		assert.Len(t, chunkFiles, 2)

		// Second chunk should only contain line 4 (line 1 modification was dropped).
		content, err := os.ReadFile(chunkFiles[1])
		require.NoError(t, err)
		assert.Equal(t, "new line 4\n", string(content))
	})
}

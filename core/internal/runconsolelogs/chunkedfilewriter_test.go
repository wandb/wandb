package runconsolelogs_test

import (
	"fmt"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/paths"
	. "github.com/wandb/wandb/core/internal/runconsolelogs"
	"github.com/wandb/wandb/core/internal/sparselist"
	"github.com/wandb/wandb/core/internal/terminalemulator"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Helper to create a RunLogsLine with content
func makeRunLogsLine(content string) *RunLogsLine {
	return &RunLogsLine{
		LineContent: terminalemulator.LineContent{
			Content: []rune(content),
		},
	}
}

// Helper to verify chunk files exist and return their paths
func getChunkFiles(t *testing.T, tmpDir string) []string {
	files, err := filepath.Glob(filepath.Join(tmpDir, "logs", "*.log"))
	fmt.Println(files)
	require.NoError(t, err)
	sort.Strings(files) // Sort for consistent ordering
	return files
}

// FakeUploader implements the Uploader interface.
//
// The ChunkedFileWriter only calls the UploadNow method of its uploader
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

// TestChunkedFileWriterRotationBySize verifies that chunks rotate based on size.
func TestChunkedFileWriterRotationBySize(t *testing.T) {
	tmpDir := t.TempDir()
	uploader := NewFakeUploader()

	writer := NewChunkedFileWriter(ChunkedFileWriterParams{
		BaseFileName:     "output",
		OutputExtension:  ".log",
		FilesDir:         tmpDir,
		MaxChunkBytes:    100, // Small size to trigger rotation
		MaxChunkDuration: 0,   // No time-based rotation
		Uploader:         uploader,
		Logger:           observability.NewNoOpLogger(),
	})

	// Write first batch - should fit in one chunk
	changes1 := sparselist.SparseList[*RunLogsLine]{}
	changes1.Put(0, makeRunLogsLine(strings.Repeat("a", 30)))
	changes1.Put(1, makeRunLogsLine(strings.Repeat("b", 30)))
	err := writer.WriteToFile(changes1)
	assert.NoError(t, err)

	// Write second batch - should trigger rotation (total > 100 bytes)
	changes2 := sparselist.SparseList[*RunLogsLine]{}
	changes2.Put(2, makeRunLogsLine(strings.Repeat("c", 30)))
	changes2.Put(3, makeRunLogsLine(strings.Repeat("d", 30)))
	err = writer.WriteToFile(changes2)
	assert.NoError(t, err)

	// First chunk should have been uploaded during rotation
	assert.Len(t, uploader.uploadedPaths, 1)

	// Write more data to create the second chunk file
	changes3 := sparselist.SparseList[*RunLogsLine]{}
	changes3.Put(4, makeRunLogsLine("e"))
	err = writer.WriteToFile(changes3)
	assert.NoError(t, err)

	writer.Finish()

	// Should have created 2 chunk files
	chunkFiles := getChunkFiles(t, tmpDir)
	assert.Equal(t, 2, len(chunkFiles))
	// Both should have been uploaded
	assert.Len(t, uploader.uploadedPaths, 2)
}

// TestChunkedFileWriterRotationByTime verifies that chunks rotate based on time.
func TestChunkedFileWriterRotationByTime(t *testing.T) {
	tmpDir := t.TempDir()
	uploader := NewFakeUploader()

	writer := NewChunkedFileWriter(ChunkedFileWriterParams{
		BaseFileName:     "output",
		OutputExtension:  ".log",
		FilesDir:         tmpDir,
		MaxChunkBytes:    0,                      // No size-based rotation
		MaxChunkDuration: 100 * time.Millisecond, // Short duration for testing
		Uploader:         uploader,
		Logger:           observability.NewNoOpLogger(),
	})

	// Write initial lines
	changes1 := sparselist.SparseList[*RunLogsLine]{}
	changes1.Put(0, makeRunLogsLine("first batch"))
	err := writer.WriteToFile(changes1)
	assert.NoError(t, err)

	// Wait for time threshold
	time.Sleep(150 * time.Millisecond)

	// Write more lines - should trigger time-based rotation
	changes2 := sparselist.SparseList[*RunLogsLine]{}
	changes2.Put(1, makeRunLogsLine("second batch"))
	err = writer.WriteToFile(changes2)
	assert.NoError(t, err)

	// First chunk should have been uploaded
	assert.Len(t, uploader.uploadedPaths, 1)

	// Write data to ensure second chunk file is created
	changes3 := sparselist.SparseList[*RunLogsLine]{}
	changes3.Put(2, makeRunLogsLine("more data"))
	err = writer.WriteToFile(changes3)
	assert.NoError(t, err)

	writer.Finish()

	// Should have created 2 chunk files
	chunkFiles := getChunkFiles(t, tmpDir)
	assert.Equal(t, 2, len(chunkFiles))
	// Both should have been uploaded
	assert.Len(t, uploader.uploadedPaths, 2)
}

// TestChunkedFileWriterNoRotation verifies behavior when no rotation occurs.
func TestChunkedFileWriterNoRotation(t *testing.T) {
	tmpDir := t.TempDir()
	uploader := NewFakeUploader()

	writer := NewChunkedFileWriter(ChunkedFileWriterParams{
		BaseFileName:     "output",
		OutputExtension:  ".log",
		FilesDir:         tmpDir,
		MaxChunkBytes:    10000, // Large size to prevent rotation
		MaxChunkDuration: 0,     // No time-based rotation
		Uploader:         uploader,
		Logger:           observability.NewNoOpLogger(),
	})

	// Write some data
	changes := sparselist.SparseList[*RunLogsLine]{}
	changes.Put(0, makeRunLogsLine("line 1"))
	changes.Put(1, makeRunLogsLine("line 2"))
	changes.Put(2, makeRunLogsLine("line 3"))
	err := writer.WriteToFile(changes)
	assert.NoError(t, err)

	// No uploads yet (no rotation occurred)
	assert.Len(t, uploader.uploadedPaths, 0)

	writer.Finish()

	// Should have created 1 chunk file
	chunkFiles := getChunkFiles(t, tmpDir)
	assert.Equal(t, 1, len(chunkFiles))
	// Finish should upload the final chunk
	assert.Len(t, uploader.uploadedPaths, 1)
}

// TestChunkedFileWriterNoData verifies behavior when no data is written.
func TestChunkedFileWriterNoData(t *testing.T) {
	tmpDir := t.TempDir()
	uploader := NewFakeUploader()

	writer := NewChunkedFileWriter(ChunkedFileWriterParams{
		BaseFileName:     "output",
		OutputExtension:  ".log",
		FilesDir:         tmpDir,
		MaxChunkBytes:    100,
		MaxChunkDuration: 0,
		Uploader:         uploader,
		Logger:           observability.NewNoOpLogger(),
	})

	// Finish without writing any data
	writer.Finish()

	// No files should be created
	chunkFiles := getChunkFiles(t, tmpDir)
	assert.Equal(t, 0, len(chunkFiles))
	// No uploads should occur
	assert.Len(t, uploader.uploadedPaths, 0)
}

// TestChunkedFileWriterEmptyChanges verifies handling of empty change sets.
func TestChunkedFileWriterEmptyChanges(t *testing.T) {
	tmpDir := t.TempDir()
	uploader := NewFakeUploader()

	writer := NewChunkedFileWriter(ChunkedFileWriterParams{
		BaseFileName:     "output",
		OutputExtension:  ".log",
		FilesDir:         tmpDir,
		MaxChunkBytes:    100,
		MaxChunkDuration: 0,
		Uploader:         uploader,
		Logger:           observability.NewNoOpLogger(),
	})

	// Write empty changes
	emptyChanges := sparselist.SparseList[*RunLogsLine]{}
	err := writer.WriteToFile(emptyChanges)
	assert.NoError(t, err)

	// Write actual data
	changes := sparselist.SparseList[*RunLogsLine]{}
	changes.Put(0, makeRunLogsLine("content"))
	err = writer.WriteToFile(changes)
	assert.NoError(t, err)

	writer.Finish()

	// Should have 1 file and 1 upload
	chunkFiles := getChunkFiles(t, tmpDir)
	assert.Equal(t, 1, len(chunkFiles))
	assert.Len(t, uploader.uploadedPaths, 1)
}

// TestChunkedFileWriterBothSizeAndTime verifies rotation with both size and time limits.
func TestChunkedFileWriterBothSizeAndTime(t *testing.T) {
	tmpDir := t.TempDir()
	uploader := NewFakeUploader()

	writer := NewChunkedFileWriter(ChunkedFileWriterParams{
		BaseFileName:     "output",
		OutputExtension:  ".log",
		FilesDir:         tmpDir,
		MaxChunkBytes:    200,                    // Size limit
		MaxChunkDuration: 100 * time.Millisecond, // Time limit
		Uploader:         uploader,
		Logger:           observability.NewNoOpLogger(),
	})

	// Test 1: Size-based rotation should happen first
	changes1 := sparselist.SparseList[*RunLogsLine]{}
	for i := range 5 {
		changes1.Put(i, makeRunLogsLine(strings.Repeat("x", 50)))
	}
	err := writer.WriteToFile(changes1)
	assert.NoError(t, err)

	// Should have rotated due to size
	assert.Len(t, uploader.uploadedPaths, 1)

	// Write small data to create new chunk
	changes2 := sparselist.SparseList[*RunLogsLine]{}
	changes2.Put(5, makeRunLogsLine("small"))
	err = writer.WriteToFile(changes2)
	assert.NoError(t, err)

	// Wait for time limit
	time.Sleep(150 * time.Millisecond)

	// Trigger rotation check with another write
	changes3 := sparselist.SparseList[*RunLogsLine]{}
	changes3.Put(6, makeRunLogsLine("trigger"))
	err = writer.WriteToFile(changes3)
	assert.NoError(t, err)

	// Should have rotated due to time
	assert.Len(t, uploader.uploadedPaths, 2)

	// Write data to create third chunk
	changes4 := sparselist.SparseList[*RunLogsLine]{}
	changes4.Put(7, makeRunLogsLine("final"))
	err = writer.WriteToFile(changes4)
	assert.NoError(t, err)

	writer.Finish()

	// Should have at least 3 chunks total
	chunkFiles := getChunkFiles(t, tmpDir)
	assert.GreaterOrEqual(t, len(chunkFiles), 3)
	assert.Equal(t, len(chunkFiles), len(uploader.uploadedPaths))
}

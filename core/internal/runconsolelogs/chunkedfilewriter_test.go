package runconsolelogs_test

import (
	"fmt"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runconsolelogs"
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

	writer := runconsolelogs.NewChunkedFileWriter(runconsolelogs.ChunkedFileWriterParams{
		BaseFileName:    "output",
		OutputExtension: ".log",
		FilesDir:        tmpDir,
		MaxChunkBytes:   100, // Small size to trigger rotation
		MaxChunkSeconds: 0,   // No time-based rotation
		Uploader:        uploader,
		Logger:          observability.NewNoOpLogger(),
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

	writer.Finish()

	// Should have created 2 chunk files.
	chunkFiles := getChunkFiles(t, tmpDir)
	assert.Equal(t, 2, len(chunkFiles))
	// Both should have been uploaded.
	assert.Len(t, uploader.uploadedPaths, 2)
}

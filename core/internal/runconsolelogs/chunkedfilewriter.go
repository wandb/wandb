package runconsolelogs

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/sparselist"
)

// chunkedFileWriter saves run console logs in multiple chunked files.
//
// This writer splits console output into multiple files based on size and time
// thresholds. Each chunk is uploaded independently, allowing console logs to be
// available during long-running jobs and preserving logs in case of crashes.
//
// The writer maintains global line number consistency across chunks to ensure
// proper reconstruction of the complete log file.
type chunkedFileWriter struct {
	mu sync.Mutex

	// Current chunk state
	currentChunk     *lineFile
	currentChunkPath paths.RelativePath
	currentSize      int64
	chunkStartTime   time.Time

	// Global line tracking for offset management
	globalLineOffset int // Starting line number for current chunk
	nextGlobalLine   int // Next line number to be written globally

	// Configuration
	maxChunkBytes    int64
	maxChunkDuration time.Duration

	// Dependencies
	filesDir string
	uploader runfiles.Uploader
	logger   *observability.CoreLogger

	// Chunk naming
	baseFileName    string
	outputExtension string
	chunkIndex      int
}

// chunkedFileWriterParams contains parameters for creating a chunkedFileWriter.
type ChunkedFileWriterParams struct {
	BaseFileName     string
	OutputExtension  string
	FilesDir         string
	MaxChunkBytes    int64
	MaxChunkDuration time.Duration
	Uploader         runfiles.Uploader
	Logger           *observability.CoreLogger
}

// newChunkedFileWriter creates a new chunked file writer.
//
// The writer delays creating the first chunk file until the first write,
// ensuring accurate timestamps for chunk naming.
func NewChunkedFileWriter(params ChunkedFileWriterParams) *chunkedFileWriter {
	return &chunkedFileWriter{
		baseFileName:     params.BaseFileName,
		outputExtension:  params.OutputExtension,
		filesDir:         params.FilesDir,
		maxChunkBytes:    params.MaxChunkBytes,
		maxChunkDuration: params.MaxChunkDuration,
		uploader:         params.Uploader,
		logger:           params.Logger,
	}
}

// WriteToFile writes console log changes to the current chunk file.
//
// This method handles line number offset translation from global to chunk-local
// coordinates and triggers chunk rotation when size or time limits are exceeded.
func (w *chunkedFileWriter) WriteToFile(
	changes sparselist.SparseList[*RunLogsLine],
) error {
	if changes.Len() == 0 {
		return nil
	}

	w.mu.Lock()
	defer w.mu.Unlock()

	// Create first chunk on first write, or create new chunk after rotation
	if w.currentChunk == nil {
		if err := w.createNewChunk(); err != nil {
			return fmt.Errorf("failed to create chunk: %v", err)
		}
	}

	// Convert RunLogsLine to string and track line numbers
	lines := sparselist.SparseList[string]{}
	var addedBytes int64

	changes.ForEach(func(globalLineNum int, line *RunLogsLine) {
		// Track the highest line number seen
		w.nextGlobalLine = max(w.nextGlobalLine, globalLineNum+1)

		// Convert to chunk-local line number
		localLineNum := globalLineNum - w.globalLineOffset
		if localLineNum >= 0 {
			lineStr := string(line.Content)
			lines.Put(localLineNum, lineStr)
			addedBytes += int64(len(lineStr)) + 1 // +1 for newline
		}
	})

	// Write to current chunk.
	if err := w.currentChunk.UpdateLines(lines); err != nil {
		return fmt.Errorf("failed to write to chunk: %v", err)
	}

	w.currentSize += addedBytes

	if w.shouldRotate() {
		w.rotateChunk()
	}

	return nil
}

// shouldRotate determines if the current chunk should be rotated.
func (w *chunkedFileWriter) shouldRotate() bool {
	if w.maxChunkBytes > 0 && w.currentSize >= w.maxChunkBytes {
		return true
	}
	if w.maxChunkDuration > 0 && time.Since(w.chunkStartTime) >= w.maxChunkDuration {
		return true
	}

	return false
}

// createNewChunk creates a new chunk file.
//
// This method assumes the mutex is already held by the caller.
func (w *chunkedFileWriter) createNewChunk() error {
	timestamp := time.Now()
	w.currentChunkPath = w.generateChunkPath(timestamp)

	fullPath := filepath.Join(w.filesDir, string(w.currentChunkPath))
	if err := os.MkdirAll(filepath.Dir(fullPath), os.ModePerm); err != nil {
		return err
	}

	chunk, err := CreateLineFile(fullPath, 0644)
	if err != nil {
		return fmt.Errorf("failed to create chunk file: %v", err)
	}

	w.currentChunk = chunk
	w.currentSize = 0
	w.chunkStartTime = timestamp
	w.chunkIndex++

	return nil
}

// rotateChunk uploads the current chunk and creates a new one.
//
// This method should be called synchronously while holding the w.mu lock.
func (w *chunkedFileWriter) rotateChunk() {
	// Upload the current chunk
	w.uploader.UploadNow(w.currentChunkPath, filetransfer.RunFileKindWandb)

	// Update offset for next chunk
	w.globalLineOffset = w.nextGlobalLine

	// Clear current chunk state - next write will create new chunk
	w.currentChunk = nil
	w.currentChunkPath = ""
	w.currentSize = 0
}

// Finish uploads any remaining data in the current chunk.
//
// This method should be called before the filestream is closed to ensure
// all console output is uploaded.
func (w *chunkedFileWriter) Finish() {
	w.mu.Lock()
	defer w.mu.Unlock()

	// Only upload if we have a current chunk with data
	if w.currentChunk != nil && w.currentChunkPath != "" {
		w.uploader.UploadNow(w.currentChunkPath, filetransfer.RunFileKindWandb)
	}
}

// generateChunkPath generates a timestamped chunk file path.
//
// The path format is: logs/baseFileName_YYYYMMDD_HHMMSS_nnnnnnnnn.extension
// where nnnnnnnnn is the nanosecond portion for uniqueness.
func (w *chunkedFileWriter) generateChunkPath(timestamp time.Time) paths.RelativePath {
	filename := fmt.Sprintf(
		"%s_%s_%09d%s",
		w.baseFileName,
		timestamp.Format("20060102_150405"),
		timestamp.Nanosecond(),
		w.outputExtension,
	)

	// This is guaranteed not to fail based on the format
	path, _ := paths.Relative(filepath.Join("logs", filename))
	return *path
}

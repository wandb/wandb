package runconsolelogs

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/sparselist"
)

// outputFileWriter saves run console logs on disk.
//
// If multipart is false, it writes a single file in filesDir.
// If multipart is true, it splits console output into multiple timestamped
// files based on size and time thresholds and writes them to filesDir/logs.
// Chunks are uploaded on file rotation and/or on Finish.
type outputFileWriter struct {
	mu sync.Mutex

	// Output file naming.
	filesDir        string
	baseFileName    string
	outputExtension string

	// Chunking configuration.
	multipart        bool
	maxChunkBytes    int64
	maxChunkDuration time.Duration

	// Current chunk state.
	currentChunk             *lineFile
	currentChunkRelativePath paths.RelativePath
	currentSize              int64
	chunkStartTime           time.Time

	// Global line tracking for offset management.
	currentChunkLineOffset int // Starting line number for current chunk.
	nextGlobalLine         int // Next line number to be written globally.

	// broken indicates whether an error occured in WriteToFile.
	//
	// When true, WriteToFile is a no-op.
	broken bool

	uploader runfiles.Uploader
}

// OutputFileWriterParams contains parameters for creating an outputFileWriter.
type OutputFileWriterParams struct {
	FilesDir         string
	OutputFileName   string
	Multipart        bool
	MaxChunkBytes    int64
	MaxChunkDuration time.Duration
	Uploader         runfiles.Uploader
}

func NewOutputFileWriter(params OutputFileWriterParams) *outputFileWriter {
	extension := filepath.Ext(string(params.OutputFileName))
	baseFileName := strings.TrimSuffix(string(params.OutputFileName), extension)

	return &outputFileWriter{
		filesDir:         params.FilesDir,
		baseFileName:     baseFileName,
		outputExtension:  extension,
		multipart:        params.Multipart,
		maxChunkBytes:    params.MaxChunkBytes,
		maxChunkDuration: params.MaxChunkDuration,
		uploader:         params.Uploader,
	}
}

// WriteToFile writes console log changes to the current chunk file.
//
// This method handles line number offset translation from global to chunk-local
// coordinates and triggers chunk rotation when size or time limits are exceeded.
//
// If w.broken is true, this is a no-op.
func (w *outputFileWriter) WriteToFile(
	changes sparselist.SparseList[*RunLogsLine],
) error {
	if w.broken {
		return nil
	}

	if changes.Len() == 0 {
		return nil
	}

	w.mu.Lock()
	defer w.mu.Unlock()

	// Create first chunk on first write, or create new chunk after rotation.
	if w.currentChunk == nil {
		if err := w.createNewChunk(); err != nil {
			w.broken = true
			return fmt.Errorf("failed to create chunk: %v", err)
		}
	}

	lines := sparselist.SparseList[string]{}
	var addedBytes int64

	changes.ForEach(func(globalLineNum int, line *RunLogsLine) {
		// Track the highest line number seen.
		w.nextGlobalLine = max(w.nextGlobalLine, globalLineNum+1)

		// Convert to chunk-local line number.
		localLineNum := globalLineNum - w.currentChunkLineOffset
		if localLineNum >= 0 {
			lineStr := string(line.Content)
			lines.Put(localLineNum, lineStr)
			addedBytes += int64(len(lineStr)) + 1 // +1 for newline
		}
	})

	if err := w.currentChunk.UpdateLines(lines); err != nil {
		w.broken = true
		return fmt.Errorf("failed to write to chunk: %v", err)
	}

	// This is an estimate as UpdateLines could pop or replay lines near the end.
	w.currentSize += addedBytes

	if w.shouldRotate() {
		w.rotateChunk()
	}

	return nil
}

// shouldRotate determines if the current chunk should be rotated.
func (w *outputFileWriter) shouldRotate() bool {
	switch {
	case !w.multipart:
		return false
	case w.maxChunkBytes > 0 && w.currentSize >= w.maxChunkBytes:
		return true
	case w.maxChunkDuration > 0 && time.Since(w.chunkStartTime) >= w.maxChunkDuration:
		return true
	default:
		return false
	}
}

// createNewChunk creates a new chunk file.
//
// This method assumes the mutex is already held by the caller.
func (w *outputFileWriter) createNewChunk() error {
	timestamp := time.Now()
	p, err := w.generateChunkPath(timestamp)
	if err != nil {
		return err
	}
	w.currentChunkRelativePath = *p

	fullPath := filepath.Join(w.filesDir, string(w.currentChunkRelativePath))
	if err := os.MkdirAll(filepath.Dir(fullPath), os.ModePerm); err != nil {
		return err
	}

	// 6 = read, write permissions for the user.
	// 4 = read-only for "group" and "other".
	chunk, err := CreateLineFile(fullPath, 0644)
	if err != nil {
		return fmt.Errorf("failed to create chunk file: %v", err)
	}

	w.currentChunk = chunk
	w.currentSize = 0
	w.chunkStartTime = timestamp

	return nil
}

// rotateChunk uploads the current chunk and creates a new one.
//
// This method should be called synchronously while holding the w.mu lock.
func (w *outputFileWriter) rotateChunk() {
	// Schedule the uploading of the current chunk.
	w.uploader.UploadNow(w.currentChunkRelativePath, filetransfer.RunFileKindWandb)

	// Update offset for next chunk.
	w.currentChunkLineOffset = w.nextGlobalLine

	// Clear current chunk state - next write will create new chunk.
	w.currentChunk = nil
	w.currentChunkRelativePath = ""
	w.currentSize = 0
}

// Finish uploads any remaining data in the current chunk.
//
// This method should be called before the filestream is closed to ensure
// all console output is uploaded.
func (w *outputFileWriter) Finish() {
	var path paths.RelativePath

	w.mu.Lock()
	if w.currentChunk != nil && w.currentChunkRelativePath != "" {
		path = w.currentChunkRelativePath
		// Clear state so repeated Finish() calls are no-ops.
		w.currentChunk = nil
		w.currentChunkRelativePath = ""
		w.currentSize = 0
	}
	w.mu.Unlock()

	if path != "" {
		w.uploader.UploadNow(path, filetransfer.RunFileKindWandb)
	}
}

// generateChunkPath generates a chunk file path.
func (w *outputFileWriter) generateChunkPath(timestamp time.Time) (*paths.RelativePath, error) {
	if !w.multipart {
		return paths.Relative(w.baseFileName + w.outputExtension)
	}

	filename := fmt.Sprintf(
		"%s_%s_%09d%s",
		w.baseFileName,
		timestamp.Format("20060102_150405"),
		timestamp.Nanosecond(),
		w.outputExtension,
	)

	// TODO: add an index if for some reason it already exists.

	return paths.Relative(filepath.Join("logs", filename))
}

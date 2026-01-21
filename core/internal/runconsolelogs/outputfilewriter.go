package runconsolelogs

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"golang.org/x/time/rate"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/sparselist"
)

const (
	// outputFileDebounceTime is how long to wait before flushing to disk.
	//
	// On distributed filesystems, open() and close() calls can be expensive.
	// We only upload output.log at the end of a run (or at an infrequent rate
	// if chunking), and the only reason to flush data to disk before then
	// is to limit RAM usage.
	//
	// Note on chunking: we may exceed the chunking duration by this amount
	// of time, uploading a chunk a little later than specified.
	outputFileDebounceTime = 5 * time.Second
)

// outputFileWriter saves run console logs on disk.
//
// If multipart is false, it writes a single file in filesDir.
// If multipart is true, it splits console output into multiple timestamped
// files based on size and time thresholds and writes them to filesDir/logs.
// Chunks are uploaded on file rotation and/or on Finish.
type outputFileWriter struct {
	mu sync.Mutex

	// debouncer batches updates to avoid hitting the filesystem too frequently.
	debouncer *debouncedWriter

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

	// broken indicates whether an error occured in writeToFile.
	//
	// When true, writeToFile is a no-op.
	broken bool

	logger        *observability.CoreLogger
	uploaderOrNil runfiles.Uploader
}

// OutputFileWriterParams contains parameters for creating an outputFileWriter.
type OutputFileWriterParams struct {
	FilesDir         string
	OutputFileName   string
	Multipart        bool
	MaxChunkBytes    int64
	MaxChunkDuration time.Duration

	Logger        *observability.CoreLogger
	UploaderOrNil runfiles.Uploader
}

func NewOutputFileWriter(params OutputFileWriterParams) *outputFileWriter {
	extension := filepath.Ext(string(params.OutputFileName))
	baseFileName := strings.TrimSuffix(string(params.OutputFileName), extension)

	fileWriter := &outputFileWriter{
		filesDir:         params.FilesDir,
		baseFileName:     baseFileName,
		outputExtension:  extension,
		multipart:        params.Multipart,
		maxChunkBytes:    params.MaxChunkBytes,
		maxChunkDuration: params.MaxChunkDuration,

		logger:        params.Logger,
		uploaderOrNil: params.UploaderOrNil,
	}

	fileWriter.debouncer = NewDebouncedWriter(
		rate.NewLimiter(rate.Every(outputFileDebounceTime), 1),
		fileWriter.writeToFile,
	)

	return fileWriter
}

// UpdateLine schedules a debounced update to the current chunk file.
func (w *outputFileWriter) UpdateLine(lineNum int, line *RunLogsLine) {
	w.debouncer.OnChanged(lineNum, line)
}

// writeToFile writes console log changes to the current chunk file.
//
// This method handles line number offset translation from global to chunk-local
// coordinates and triggers chunk rotation when size or time limits are exceeded.
//
// If w.broken is true, this is a no-op.
func (w *outputFileWriter) writeToFile(
	changes *sparselist.SparseList[*RunLogsLine],
) {
	if w.broken {
		return
	}

	if changes.Len() == 0 {
		return
	}

	w.mu.Lock()
	defer w.mu.Unlock()

	// Create first chunk on first write, or create new chunk after rotation.
	if w.currentChunk == nil {
		if err := w.createNewChunk(); err != nil {
			w.broken = true
			w.logger.CaptureError(
				fmt.Errorf("runconsolelogs: failed to create chunk: %v", err))
			return
		}
	}

	lines := &sparselist.SparseList[string]{}
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
		w.logger.CaptureError(fmt.Errorf("failed to write to chunk: %v", err))
		return
	}

	// This is an estimate as UpdateLines could pop or replay lines near the end.
	w.currentSize += addedBytes

	if w.shouldRotate() {
		w.rotateChunk()
	}
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
	chunk, err := CreateLineFile(fullPath, 0o644)
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
	if w.uploaderOrNil != nil {
		w.uploaderOrNil.UploadNow(
			w.currentChunkRelativePath,
			filetransfer.RunFileKindWandb,
		)
	}

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
	w.debouncer.Finish()

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

	if path != "" && w.uploaderOrNil != nil {
		w.uploaderOrNil.UploadNow(path, filetransfer.RunFileKindWandb)
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

package runconsolelogs

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/sparselist"
)

type outputFileWriterParams struct {
	filesDir       string
	outputFileName *paths.RelativePath
	logger         *observability.CoreLogger
	multipart      bool
	chunkBytes     int32
	chunkSeconds   int32
	onRotate       func(currentOutputFileName *paths.RelativePath)
}

// outputFileWriter saves run console logs in a local file.
type outputFileWriter struct {
	outputFile *lineFile

	filesDir              string
	baseOutputFileName    *paths.RelativePath
	currentOutputFileName *paths.RelativePath
	logger                *observability.CoreLogger

	multipart     bool
	bytesWritten  int64
	partStartedAt time.Time
	chunkBytes    int32
	chunkDur      time.Duration
	// Callback so caller can swap to the new file path.
	onRotate func(currentOutputFileName *paths.RelativePath)
}

func NewOutputFileWriter(params outputFileWriterParams) (*outputFileWriter, error) {
	baseOutputFileName := params.outputFileName
	currentOutputFileName := params.outputFileName

	if params.multipart {
		currentOutputFileName = makeTimestampedPath(baseOutputFileName)
	}

	ofw := &outputFileWriter{logger: params.logger}

	lf, err := createLineFile(params.filesDir, *currentOutputFileName)
	ofw.outputFile = lf
	if err != nil {
		return nil, err
	}

	ofw.filesDir = params.filesDir
	ofw.baseOutputFileName = baseOutputFileName
	ofw.currentOutputFileName = currentOutputFileName

	ofw.chunkBytes = params.chunkBytes
	ofw.chunkDur = time.Duration(params.chunkSeconds) * time.Second
	ofw.partStartedAt = time.Now()
	ofw.onRotate = params.onRotate

	return ofw, nil
}

func createLineFile(filesDir string, rel paths.RelativePath) (*lineFile, error) {

	abs := filepath.Join(filesDir, string(rel))
	if err := os.MkdirAll(filepath.Dir(abs), os.ModePerm); err != nil {
		return nil, err
	}

	// 6 = read, write permissions for the user.
	// 4 = read-only for "group" and "other".
	lf, err := CreateLineFile(abs, 0644)
	if err != nil {
		return nil, err
	}
	return lf, nil
}

// WriteToFile makes changes to the underlying file.
//
// It returns an error if writing fails, such as if the file is deleted
// or corrupted. In that case, the file should not be written to again.
func (w *outputFileWriter) WriteToFile(
	changes sparselist.SparseList[*RunLogsLine],
) error {
	fmt.Println("+++ changes to write:\n", changes)
	lines := sparselist.Map(changes, func(line *RunLogsLine) string {
		return string(line.Content)
	})
	fmt.Println("+++ lines:\n", lines)

	if err := w.outputFile.UpdateLines(lines); err != nil {
		return err
	}
	// TODO: count written bytes
	// w.bytesWritten += int64(lines.LenAddedBytes())

	if w.shouldRotate() {
		w.rotate()
	}
	return nil
}

func (w *outputFileWriter) shouldRotate() bool {
	if w.chunkBytes > 0 && w.bytesWritten >= int64(w.chunkBytes) {
		return true
	}
	if w.chunkDur > 0 && time.Since(w.partStartedAt) >= w.chunkDur {
		return true
	}
	return false
}

func (w *outputFileWriter) rotate() {
	// close current
	_ = w.outputFile.UpdateLines(sparselist.SparseList[string]{})
	// Reset counters.
	w.bytesWritten = 0
	w.partStartedAt = time.Now()

	// create next part
	newRel := makeTimestampedPath(w.baseOutputFileName)
	lf, err := createLineFile(w.filesDir, *newRel)
	if err != nil {
		w.logger.CaptureError(fmt.Errorf("runconsolelogs: rotating console log failed: %v", err))
		return
	}
	// Swap in the line file.
	w.outputFile = lf

	if w.onRotate != nil {
		w.onRotate(w.currentOutputFileName)
		// Swap in the pointer to the current file being written to.
		*w.currentOutputFileName = *newRel
	}
}

// makeTimestampedPath creates a timestamped path under the `logs/` directory.
//
// Used when multipart console log capture is enabled.
func makeTimestampedPath(base *paths.RelativePath) *paths.RelativePath {
	ts := time.Now()
	ext := filepath.Ext(string(*base))
	p, _ := paths.Relative(filepath.Join(
		"logs",
		fmt.Sprintf("%s_%s_%09d%s",
			strings.TrimSuffix(string(*base), ext),
			ts.Format("20060102_150405"),
			ts.Nanosecond(),
			ext),
	))
	return p
}

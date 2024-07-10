package runconsolelogs

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/sparselist"
	"github.com/wandb/wandb/core/pkg/observability"
)

// outputFileWriter saves run console logs in a local file.
type outputFileWriter struct {
	outputFile *lineFile
	logger     *observability.CoreLogger
}

func NewOutputFileWriter(
	path string,
	logger *observability.CoreLogger,
) (*outputFileWriter, error) {
	if err := os.MkdirAll(filepath.Dir(path), os.ModePerm); err != nil {
		return nil, err
	}

	// 6 = read, write permissions for the user.
	// 4 = read-only for "group" and "other".
	outputFile, err := CreateLineFile(path, 0644)
	if err != nil {
		return nil, err
	}

	return &outputFileWriter{outputFile: outputFile, logger: logger}, nil
}

func (w *outputFileWriter) WriteToFile(
	changes sparselist.SparseList[*RunLogsLine],
) {
	lines := sparselist.Map(changes, func(line *RunLogsLine) string {
		return string(line.Content)
	})

	err := w.outputFile.UpdateLines(lines)
	if err != nil {
		w.logger.CaptureError(
			fmt.Errorf(
				"runconsolelogs: failed to write to file: %v",
				err,
			))
	}
}

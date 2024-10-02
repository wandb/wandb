package runconsolelogs

import (
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sparselist"
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

// WriteToFile makes changes to the underlying file.
//
// It returns an error if writing fails, such as if the file is deleted
// or corrupted. In that case, the file should not be written to again.
func (w *outputFileWriter) WriteToFile(
	changes sparselist.SparseList[*RunLogsLine],
) error {
	lines := sparselist.Map(changes, func(line *RunLogsLine) string {
		return string(line.Content)
	})

	return w.outputFile.UpdateLines(lines)
}

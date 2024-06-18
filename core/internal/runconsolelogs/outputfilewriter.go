package runconsolelogs

import (
	"fmt"
	"sync"

	"github.com/wandb/wandb/core/internal/sparselist"
	"github.com/wandb/wandb/core/pkg/observability"
)

// outputFileWriter saves run console logs in a local file.
type outputFileWriter struct {
	outputFile *lineFile
	logger     *observability.CoreLogger

	wg            sync.WaitGroup
	mu            sync.Mutex
	bufferedLines sparselist.SparseList[string]
	isWriting     bool
}

func NewOutputFileWriter(
	path string,
	logger *observability.CoreLogger,
) (*outputFileWriter, error) {
	// 6 = read, write permissions for the user.
	// 4 = read-only for "group" and "other".
	outputFile, err := CreateLineFile(path, 0644)
	if err != nil {
		return nil, err
	}

	return &outputFileWriter{outputFile: outputFile, logger: logger}, nil
}

func (w *outputFileWriter) Finish() {
	w.wg.Wait()
}

func (w *outputFileWriter) WriteToFile(lineNum int, line RunLogsLine) {
	w.mu.Lock()
	defer w.mu.Unlock()

	w.bufferedLines.Put(lineNum, string(line.Content))

	if !w.isWriting {
		w.isWriting = true

		w.wg.Add(1)
		go func() {
			for {
				w.mu.Lock()
				if w.bufferedLines.Len() == 0 {
					break
				}
				lines := w.bufferedLines
				w.bufferedLines = sparselist.SparseList[string]{}
				w.mu.Unlock()

				w.flush(lines)
			}

			w.wg.Done()
			w.isWriting = false
			w.mu.Unlock()
		}()
	}
}

func (w *outputFileWriter) flush(lines sparselist.SparseList[string]) {
	err := w.outputFile.UpdateLines(lines)
	if err != nil {
		w.logger.CaptureError(
			fmt.Errorf(
				"runconsolelogs: failed to write to file: %v",
				err,
			))
	}
}

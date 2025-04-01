package runfiles

import (
	"fmt"
	"os"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
)

// FileCleaner handles deleting files.
type FileCleaner struct {
	// Channel for file paths to delete
	deleteChan chan string
	// WaitGroup to track goroutine completion
	wg sync.WaitGroup
	// Logger for error reporting
	logger *observability.CoreLogger
}

func NewFileCleaner(logger *observability.CoreLogger) *FileCleaner {
	fc := &FileCleaner{
		deleteChan: make(chan string),
		logger:     logger,
	}
	fc.start()
	return fc
}

func (fc *FileCleaner) start() {
	fc.wg.Add(1)
	go func() {
		defer fc.wg.Done()

		for filepath := range fc.deleteChan {
			if err := os.RemoveAll(filepath); err != nil {
				fc.logger.CaptureError(
					fmt.Errorf("filecleaner: failed to delete: %v", err),
					"path: ",
					filepath,
				)
			} else {
				fc.logger.Debug("filecleaner: deleted file", "path", filepath)
			}
		}
		fc.logger.Info("filecleaner: stopped")
	}()
}

func (fc *FileCleaner) Close() {
	close(fc.deleteChan)
	fc.wg.Wait()
}

// ScheduleDeleteFile adds a file to the deletion queue
func (fc *FileCleaner) ScheduleDeleteFile(filepath string) {
	fc.logger.Debug("filecleaner: scheduling deletion of file", "path", filepath)
	fc.deleteChan <- filepath
}

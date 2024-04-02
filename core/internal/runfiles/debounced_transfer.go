package runfiles

import (
	"os"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/pkg/observability"
)

// debouncedTransfer wraps a FileTransferManager to avoid reuploading
// unmodified files.
type debouncedTransfer struct {
	sync.Mutex

	ftm filetransfer.FileTransferManager

	logger *observability.CoreLogger

	// The modification time of each file at its last upload.
	lastUploadedModTime map[string]time.Time
}

func newDebouncedTransfer(
	ftm filetransfer.FileTransferManager,
	logger *observability.CoreLogger,
) *debouncedTransfer {
	return &debouncedTransfer{
		ftm:                 ftm,
		logger:              logger,
		lastUploadedModTime: make(map[string]time.Time),
	}
}

// AddTask queues a file upload task unless it's unnecessary.
func (t *debouncedTransfer) AddTask(task *filetransfer.Task) {
	t.Lock()
	defer t.Unlock()

	info, err := os.Stat(task.Path)
	if err != nil {
		t.logger.Error(
			"runfiles: failed to stat file; not uploading",
			"file", task.Path,
		)
		task.CompletionCallback(task)
		return
	}

	if !info.ModTime().After(t.lastUploadedModTime[task.Path]) {
		t.logger.Debug(
			"runfiles: skipping upload because file is up to date",
			"file", task.Path,
		)
		task.CompletionCallback(task)
		return
	}

	t.lastUploadedModTime[task.Path] = info.ModTime()

	t.ftm.AddTask(task)
}

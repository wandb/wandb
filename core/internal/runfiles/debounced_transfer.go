package runfiles

import (
	"os"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/pkg/observability"
)

// debouncedTransfer wraps a FileTransferManager to avoid uploading files
// too often.
//
// Specifically:
//   - Files which have not been modified are not reuploaded
//   - Files for which an upload is currently in progress are not reuploaded
type debouncedTransfer struct {
	sync.Mutex

	ftm filetransfer.FileTransferManager

	logger *observability.CoreLogger

	// The modification time of each file at its last upload.
	lastUploadedModTime map[string]time.Time

	// Files that are currently being uploaded.
	inProgressSet map[string]struct{}

	// File uploads that are waiting for a previous upload to complete.
	bufferedTasks map[string]*filetransfer.Task
}

func newDebouncedTransfer(
	ftm filetransfer.FileTransferManager,
	logger *observability.CoreLogger,
) *debouncedTransfer {
	return &debouncedTransfer{
		ftm:                 ftm,
		logger:              logger,
		lastUploadedModTime: make(map[string]time.Time),
		inProgressSet:       make(map[string]struct{}),
		bufferedTasks:       make(map[string]*filetransfer.Task),
	}
}

// AddTask queues a file upload task unless it's unnecessary.
func (t *debouncedTransfer) AddTask(task *filetransfer.Task) {
	if t.prepareTask(task) {
		t.ftm.AddTask(task)
	}
}

// prepareTask prepares a task to be sent to the file transfer manager and
// reports whether it should be sent.
//
// It mainly exists as a separate function because we don't want to hold
// the mutex when we call FileTransferManager's AddTask() as it could cause
// a deadlock.
func (t *debouncedTransfer) prepareTask(task *filetransfer.Task) bool {
	t.Lock()
	defer t.Unlock()

	// If there's an in-progress upload, wait for it to finish first.
	if _, inProgress := t.inProgressSet[task.Path]; inProgress {
		t.bufferedTasks[task.Path] = task
		return false
	}

	// Finish immediately if the file hasn't been changed since last upload.
	info, err := os.Stat(task.Path)
	if err != nil {
		t.logger.Error(
			"runfiles: failed to stat file; not uploading",
			"file", task.Path,
		)
		task.CompletionCallback(task)
		return false
	}

	if !info.ModTime().After(t.lastUploadedModTime[task.Path]) {
		t.logger.Debug(
			"runfiles: skipping upload because file is up to date",
			"file", task.Path,
		)
		task.CompletionCallback(task)
		return false
	}

	t.lastUploadedModTime[task.Path] = info.ModTime()

	// On completion, check the buffered list of tasks.
	oldCompletionCallback := task.CompletionCallback
	task.SetCompletionCallback(func(_ *filetransfer.Task) {
		oldCompletionCallback(task)

		delete(t.inProgressSet, task.Path)

		t.Lock()
		next, hasNext := t.bufferedTasks[task.Path]
		delete(t.bufferedTasks, task.Path)
		t.Unlock()

		if hasNext {
			t.AddTask(next)
		}
	})

	t.inProgressSet[task.Path] = struct{}{}
	return true
}

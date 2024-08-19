package filetransfer

import (
	"fmt"
	"sync"

	"github.com/wandb/wandb/core/pkg/observability"
)

type Storage int

const (
	bufferSize              = 32
	DefaultConcurrencyLimit = 128
)

// FileTransferManager uploads and downloads files.
type FileTransferManager interface {
	// AddTask schedules a file upload or download operation.
	AddTask(task Task)

	// Close waits for all tasks to complete.
	Close()
}

// FileTransferManager handles the upload/download of files
type fileTransferManager struct {
	// fileTransfers is the map of fileTransfer uploader/downloaders
	fileTransfers *FileTransfers

	// fileTransferStats keeps track of upload/download statistics
	fileTransferStats FileTransferStats

	// semaphore is the semaphore for limiting concurrency
	semaphore chan struct{}

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// wg is the wait group
	wg *sync.WaitGroup
}

type FileTransferManagerOption func(fm *fileTransferManager)

func WithLogger(logger *observability.CoreLogger) FileTransferManagerOption {
	return func(fm *fileTransferManager) {
		fm.logger = logger
	}
}

func WithFileTransfers(fileTransfers *FileTransfers) FileTransferManagerOption {
	return func(fm *fileTransferManager) {
		fm.fileTransfers = fileTransfers
	}
}

func WithFileTransferStats(fileTransferStats FileTransferStats) FileTransferManagerOption {
	return func(fm *fileTransferManager) {
		fm.fileTransferStats = fileTransferStats
	}
}

func NewFileTransferManager(opts ...FileTransferManagerOption) FileTransferManager {

	fm := fileTransferManager{
		wg:        &sync.WaitGroup{},
		semaphore: make(chan struct{}, DefaultConcurrencyLimit),
	}

	for _, opt := range opts {
		opt(&fm)
	}

	return &fm
}

func (fm *fileTransferManager) AddTask(task Task) {
	fm.logger.Debug("fileTransfer: adding upload task", "path", task.GetPath(), "url", task.GetUrl())

	fm.wg.Add(1)
	go func() {
		defer fm.wg.Done()

		// Guard by a semaphore to limit number of concurrent uploads.
		fm.semaphore <- struct{}{}
		task.SetErr(fm.transfer(task))
		<-fm.semaphore

		if task.GetErr() != nil {
			fm.logger.CaptureError(
				fmt.Errorf(
					"filetransfer: uploader: error uploading to %v: %v",
					task.GetUrl(),
					task.GetErr(),
				),
				"path", task.GetPath(),
			)
		}

		// Execute the callback.
		fm.completeTask(task)
	}()
}

// completeTask runs the completion callback and updates statistics.
func (fm *fileTransferManager) completeTask(task Task) {
	task.Complete()

	if task.GetType() == UploadTask {
		fm.fileTransferStats.UpdateUploadStats(FileUploadInfo{
			FileKind:      task.GetFileKind(),
			Path:          task.GetPath(),
			UploadedBytes: task.GetSize(),
			TotalBytes:    task.GetSize(),
		})
	}
}

func (fm *fileTransferManager) Close() {
	fm.logger.Debug("fileTransfer: Close")
	fm.wg.Wait()
}

// Uploads or downloads a file.
func (fm *fileTransferManager) transfer(task Task) error {
	return task.Execute(fm.fileTransfers)
}

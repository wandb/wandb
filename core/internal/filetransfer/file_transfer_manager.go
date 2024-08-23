package filetransfer

import (
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
	fm.logger.Debug("fileTransferManager: AddTask: adding task", "task", task.String())

	fm.wg.Add(1)
	go func() {
		defer fm.wg.Done()

		// Guard by a semaphore to limit number of concurrent uploads.
		fm.semaphore <- struct{}{}
		err := fm.transfer(task)
		task.SetError(err)
		<-fm.semaphore

		if err != nil {
			fm.logger.CaptureError(err, "task", task.String())
		}

		// Execute the callback.
		task.Complete(fm.fileTransferStats)
	}()
}

func (fm *fileTransferManager) Close() {
	fm.logger.Debug("fileTransfer: Close")
	fm.wg.Wait()
}

// Uploads or downloads a file.
func (fm *fileTransferManager) transfer(task Task) error {
	return task.Execute(fm.fileTransfers)
}

package filetransfer

import (
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
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

// FileTransferManagerOptions are the parameters for creating a new FileTransferManager
type FileTransferManagerOptions struct {
	Logger *observability.CoreLogger

	FileTransfers *FileTransfers

	FileTransferStats FileTransferStats
}

// fileTransferManager handles the upload/download of files
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

func NewFileTransferManager(opts FileTransferManagerOptions) FileTransferManager {

	return &fileTransferManager{
		wg:                &sync.WaitGroup{},
		semaphore:         make(chan struct{}, DefaultConcurrencyLimit),
		logger:            opts.Logger,
		fileTransfers:     opts.FileTransfers,
		fileTransferStats: opts.FileTransferStats,
	}
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
	fm.wg.Wait()
	fm.logger.Info("fileTransfer: Close: file transfer manager closed")
}

// Uploads or downloads a file.
func (fm *fileTransferManager) transfer(task Task) error {
	return task.Execute(fm.fileTransfers)
}

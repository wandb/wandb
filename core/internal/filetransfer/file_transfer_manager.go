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
	AddTask(task *Task)

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

func (fm *fileTransferManager) AddTask(task *Task) {
	fm.logger.Debug("fileTransfer: adding upload task", "path", task.Path, "url", task.Url)

	fm.wg.Add(1)
	go func() {
		defer fm.wg.Done()

		// Guard by a semaphore to limit number of concurrent uploads.
		fm.semaphore <- struct{}{}
		task.Err = fm.transfer(task)
		<-fm.semaphore

		if task.Err != nil {
			fm.logger.CaptureError(
				fmt.Errorf(
					"filetransfer: uploader: error uploading: %v",
					task.Err,
				),
				"url", task.Url,
				"path", task.Path,
			)
		}

		// Execute the callback.
		fm.completeTask(task)
	}()
}

// completeTask runs the completion callback and updates statistics.
func (fm *fileTransferManager) completeTask(task *Task) {
	task.CompletionCallback(task)

	if task.Type == UploadTask {
		fm.fileTransferStats.UpdateUploadStats(FileUploadInfo{
			FileKind:      task.FileKind,
			Path:          task.Path,
			UploadedBytes: task.Size,
			TotalBytes:    task.Size,
		})
	}
}

func (fm *fileTransferManager) Close() {
	fm.logger.Debug("fileTransfer: Close")
	fm.wg.Wait()
}

// Uploads or downloads a file.
func (fm *fileTransferManager) transfer(task *Task) error {
	fileTransfer := fm.fileTransfers.GetFileTransferForTask(task)
	if fileTransfer == nil {
		return fmt.Errorf("fileTransfer: no transfer for task URL %v", task.Url)
	}

	var err error
	switch task.Type {
	case UploadTask:
		err = fileTransfer.Upload(task)
	case DownloadTask:
		err = fileTransfer.Download(task)
	default:
		fm.logger.CaptureFatalAndPanic(
			fmt.Errorf("fileTransfer: unknown task type: %v", task.Type))
	}
	return err
}

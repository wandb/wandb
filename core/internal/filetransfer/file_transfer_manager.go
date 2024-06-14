package filetransfer

import (
	"fmt"
	"sync"

	"github.com/wandb/wandb/core/pkg/service"

	"github.com/wandb/wandb/core/pkg/observability"
)

type Storage int

const (
	bufferSize              = 32
	DefaultConcurrencyLimit = 128
)

// A manager of asynchronous file upload tasks.
type FileTransferManager interface {
	// Asynchronously begins the main loop of the file transfer manager.
	Start()

	// Waits for all asynchronous work to finish.
	Close()

	// Schedules a file upload operation.
	AddTask(task *Task)
}

// FileTransferManager handles the upload/download of files
type fileTransferManager struct {
	// inChan is the channel for incoming messages
	inChan chan *Task

	// fileTransfers is the map of fileTransfer uploader/downloaders
	fileTransfers *FileTransfers

	// fileTransferStats keeps track of upload/download statistics
	fileTransferStats FileTransferStats

	// semaphore is the semaphore for limiting concurrency
	semaphore chan struct{}

	// settings is the settings for the file transfer
	settings *service.Settings

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// wg is the wait group
	wg *sync.WaitGroup

	// active is true if the file transfer is active
	active bool
}

type FileTransferManagerOption func(fm *fileTransferManager)

func WithLogger(logger *observability.CoreLogger) FileTransferManagerOption {
	return func(fm *fileTransferManager) {
		fm.logger = logger
	}
}

func WithSettings(settings *service.Settings) FileTransferManagerOption {
	return func(fm *fileTransferManager) {
		fm.settings = settings
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
		inChan:    make(chan *Task, bufferSize),
		wg:        &sync.WaitGroup{},
		semaphore: make(chan struct{}, DefaultConcurrencyLimit),
	}

	for _, opt := range opts {
		opt(&fm)
	}

	return &fm
}

func (fm *fileTransferManager) Start() {
	if fm.active {
		return
	}
	fm.wg.Add(1)
	go func() {
		fm.active = true
		for task := range fm.inChan {
			// add a task to the wait group
			fm.wg.Add(1)
			fm.logger.Debug("fileTransfer: got task", "task", task.String())
			// spin up a goroutine per task
			go func(task *Task) {
				// Acquire the semaphore
				fm.semaphore <- struct{}{}
				task.Err = fm.transfer(task)
				// Release the semaphore
				<-fm.semaphore

				if task.Err != nil {
					fm.logger.CaptureError(
						fmt.Errorf(
							"filetransfer: uploader: error uploading path=%s url=%s: %v",
							task.Path,
							task.Url,
							task.Err,
						))
				}

				// Execute the callback.
				fm.completeTask(task)

				// mark the task as done
				fm.wg.Done()
			}(task)
		}
		fm.wg.Done()
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

func (fm *fileTransferManager) AddTask(task *Task) {
	fm.logger.Debug("fileTransfer: adding upload task", "path", task.Path, "url", task.Url)
	fm.inChan <- task
}

func (fm *fileTransferManager) Close() {
	if !fm.active {
		return
	}
	fm.logger.Debug("fileTransfer: Close")
	if fm.inChan == nil {
		return
	}
	// todo: review this, we don't want to cause a panic
	close(fm.inChan)
	fm.wg.Wait()
	fm.active = false
}

// Uploads or downloads a file.
func (fm *fileTransferManager) transfer(task *Task) error {
	fileTransfer := fm.fileTransfers.GetFileTransferForTask(task)
	if fileTransfer == nil {
		return fmt.Errorf("file transfer not found for task")
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

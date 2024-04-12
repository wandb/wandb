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
	defaultConcurrencyLimit = 128
)

type FileTransfer interface {
	Upload(task *Task) error
	Download(task *Task) error
}

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

	// fileTransfer is the uploader/downloader
	// todo: make this a map of uploaders for different destination storage types
	fileTransfer FileTransfer

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

func WithFileTransfer(fileTransfer FileTransfer) FileTransferManagerOption {
	return func(fm *fileTransferManager) {
		fm.fileTransfer = fileTransfer
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
		semaphore: make(chan struct{}, defaultConcurrencyLimit),
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
			fm.logger.Debug("fileTransfer: got task", "task", task)
			// spin up a goroutine per task
			go func(task *Task) {
				// Acquire the semaphore
				fm.semaphore <- struct{}{}
				task.Err = fm.transfer(task)
				// Release the semaphore
				<-fm.semaphore

				if task.Err != nil {
					fm.logger.CaptureError(
						"filetransfer: uploader: error uploading",
						task.Err,
						"path", task.Path, "url", task.Url,
					)
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
	var err error
	switch task.Type {
	case UploadTask:
		err = fm.fileTransfer.Upload(task)
	case DownloadTask:
		err = fm.fileTransfer.Download(task)
	default:
		err = fmt.Errorf("unknown task type")
		fm.logger.CaptureFatalAndPanic("fileTransfer", err)
	}
	return err
}

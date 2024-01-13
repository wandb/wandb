package filetransfer

import (
	"sync"

	"google.golang.org/protobuf/proto"

	obs "github.com/wandb/wandb/core/internal/observability"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

type Storage int

const (
	bufferSize              = 32
	defaultConcurrencyLimit = 128
)

type FileTransferer interface {
	Upload(task *Task) error
	Download(task *Task) error
}

// Manager handles the upload/download of files
type Manager struct {
	// inChan is the channel for incoming messages
	inChan chan *Task

	// fsChan is the channel for messages outgoing to the filestream
	fsChan chan proto.Message

	// transfer is the uploader/downloader
	// todo: make this a map of uploaders for different destination storage types
	transferer FileTransferer

	// semaphore is the semaphore for limiting concurrency
	semaphore chan struct{}

	// logger is the logger for the file transfer
	logger *obs.CoreLogger

	// wg is the wait group
	wg *sync.WaitGroup

	// active is true if the file transfer is active
	active bool
}

type ManagerOption func(fm *Manager)

func WithLogger(logger *obs.CoreLogger) ManagerOption {
	return func(fm *Manager) {
		fm.logger = logger
	}
}

func WithFileTransfer(transferer FileTransferer) ManagerOption {
	return func(fm *Manager) {
		fm.transferer = transferer
	}
}

func WithFSCChan(fsChan chan proto.Message) ManagerOption {
	return func(fm *Manager) {
		fm.fsChan = fsChan
	}
}

func New(opts ...ManagerOption) *Manager {

	fm := Manager{
		inChan:    make(chan *Task, bufferSize),
		wg:        &sync.WaitGroup{},
		semaphore: make(chan struct{}, defaultConcurrencyLimit),
	}

	for _, opt := range opts {
		opt(&fm)
	}

	return &fm
}

// Start is the main loop for the transfer
func (fm *Manager) Start() {
	if fm.active {
		return
	}
	fm.wg.Add(1)
	go func() {
		fm.active = true
		for task := range fm.inChan {
			// add a task to the wait group
			fm.wg.Add(1)
			fm.logger.Debug("transfer: got task", "task", task)
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
				for _, callback := range task.CompletionCallback {
					callback(task)
				}
				// mark the task as done
				fm.wg.Done()
			}(task)
		}
		fm.wg.Done()
	}()
}

// AddTask adds a task to the transfer
func (fm *Manager) AddTask(task *Task) {
	fm.logger.Debug("transfer: adding upload task", "path", task.Path, "url", task.Url)
	fm.inChan <- task
}

// FSCallback returns a callback for filestream updates
func (fm *Manager) FSCallback() func(task *Task) {
	return func(task *Task) {
		fm.logger.Debug("uploader: filestream callback", "task", task)
		if task.Err != nil {
			return
		}
		record := &pb.FilesUploaded{
			Files: []string{task.Name},
		}
		fm.fsChan <- record
	}
}

// Close closes the transfer
func (fm *Manager) Close() {
	if fm == nil {
		return
	}
	if !fm.active {
		return
	}
	fm.logger.Debug("transfer: Close")
	if fm.inChan == nil {
		return
	}
	// todo: review this, we don't want to cause a panic
	close(fm.inChan)
	fm.wg.Wait()
	fm.active = false
}

// transfer uploads/downloads a file to/from the server
func (fm *Manager) transfer(task *Task) error {
	var err error
	switch task.Type {
	case UploadTask:
		err = fm.transferer.Upload(task)
	case DownloadTask:
		err = fm.transferer.Download(task)
	default:
		fm.logger.CaptureFatalAndPanic("transfer: unknown task type", err)
	}
	return err
}

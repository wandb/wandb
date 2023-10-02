package uploader

import (
	"sync"

	"github.com/wandb/wandb/nexus/pkg/service"

	"github.com/wandb/wandb/nexus/pkg/observability"
)

type Storage int

const (
	bufferSize              = 32
	defaultConcurrencyLimit = 128
)

// type fileCounts struct {
//		wandbCount    int
//		mediaCount    int
//		artifactCount int
//		otherCount    int
// }

type Uploader interface {
	Upload(task *UploadTask) error
}

// UploadManager handles the upload of files
type UploadManager struct {
	// inChan is the channel for incoming messages
	inChan chan *UploadTask

	// uploader is the uploader
	// todo: make this a map of uploaders for different destination storage types
	uploader Uploader

	// semaphore is the semaphore for limiting concurrency
	semaphore chan struct{}

	// fileCounts is the file counts
	// fileCounts fileCounts

	// settings is the settings for the uploader
	settings *service.Settings

	// logger is the logger for the uploader
	logger *observability.NexusLogger

	// wg is the wait group
	wg *sync.WaitGroup
}

type UploadManagerOption func(um *UploadManager)

func WithLogger(logger *observability.NexusLogger) UploadManagerOption {
	return func(um *UploadManager) {
		um.logger = logger
	}
}

func WithSettings(settings *service.Settings) UploadManagerOption {
	return func(um *UploadManager) {
		um.settings = settings
	}
}

func WithUploader(uploader Uploader) UploadManagerOption {
	return func(um *UploadManager) {
		um.uploader = uploader
	}
}

func NewUploadManager(opts ...UploadManagerOption) *UploadManager {

	um := UploadManager{
		inChan: make(chan *UploadTask, bufferSize),
		wg:     &sync.WaitGroup{},
	}

	for _, opt := range opts {
		opt(&um)
	}

	um.semaphore = make(chan struct{}, defaultConcurrencyLimit)

	return &um
}

// Start is the main loop for the uploader
func (um *UploadManager) Start() {
	um.wg.Add(1)
	go func() {
		for task := range um.inChan {
			// add a task to the wait group
			um.wg.Add(1)
			um.logger.Debug("uploader: got task", "task", task)
			// spin up a goroutine per task
			go func(task *UploadTask) {
				// Acquire the semaphore
				um.semaphore <- struct{}{}
				if err := um.upload(task); err != nil {
					um.logger.CaptureError(
						"uploader: error uploading",
						err,
						"path", task.Path, "url", task.Url,
					)
				}
				// Release the semaphore
				<-um.semaphore
				// mark the task as done
				um.wg.Done()
			}(task)
		}
		um.wg.Done()
	}()
}

// AddTask adds a task to the uploader
func (um *UploadManager) AddTask(task *UploadTask) {
	task.outstandingAdd()
	um.logger.Debug("uploader: adding task", "path", task.Path, "url", task.Url)
	um.inChan <- task
}

// Close closes the uploader
func (um *UploadManager) Close() {
	if um == nil {
		return
	}
	um.logger.Debug("uploader: Close")
	if um.inChan == nil {
		return
	}
	// todo: review this, we don't want to cause a panic
	close(um.inChan)
	um.wg.Wait()
}

// upload uploads a file to the server
func (um *UploadManager) upload(task *UploadTask) error {
	err := um.uploader.Upload(task)
	return err
}

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

	// fileCounts is the file counts for the uploader
	fileCounts *service.FileCounts

	// fileCountsChan is the channel used to count files uploaded by type
	fileCountsChan chan FileType

	// wgfc is the wait group for the file counts channel ops
	wgfc *sync.WaitGroup

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

func (um *UploadManager) fileCount() {
	for fileType := range um.fileCountsChan {
		switch fileType {
		case WandbFile:
			um.fileCounts.WandbCount++
		case MediaFile:
			um.fileCounts.MediaCount++
		case ArtifactFile:
			um.fileCounts.ArtifactCount++
		default:
			um.fileCounts.OtherCount++
		}
	}
	um.wgfc.Done()
}

func NewUploadManager(opts ...UploadManagerOption) *UploadManager {

	um := UploadManager{
		inChan:         make(chan *UploadTask, bufferSize),
		fileCounts:     &service.FileCounts{},
		fileCountsChan: make(chan FileType, bufferSize),
		wgfc:           &sync.WaitGroup{},
		wg:             &sync.WaitGroup{},
		semaphore:      make(chan struct{}, defaultConcurrencyLimit),
	}

	for _, opt := range opts {
		opt(&um)
	}

	um.wgfc.Add(1)
	go um.fileCount()

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
				task.Err = um.upload(task)
				// Release the semaphore
				<-um.semaphore
				if task.Err != nil {
					um.logger.CaptureError(
						"uploader: error uploading",
						task.Err,
						"path", task.Path, "url", task.Url,
					)
				}
				// Execute the callback.
				if task.CompletionCallback != nil {
					task.CompletionCallback(task)
				}

				if task.Err == nil {
					um.fileCountsChan <- task.FileType
				}

				// mark the task as done
				um.wg.Done()
			}(task)
		}
		um.wg.Done()
	}()
}

// AddTask adds a task to the uploader
func (um *UploadManager) AddTask(task *UploadTask) {
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
	close(um.fileCountsChan)
	um.wgfc.Wait()
}

// upload uploads a file to the server
func (um *UploadManager) upload(task *UploadTask) error {
	err := um.uploader.Upload(task)
	return err
}

// GetFileCounts returns the file counts for the uploader
func (um *UploadManager) GetFileCounts() *service.FileCounts {
	if um == nil {
		return &service.FileCounts{}
	}
	return um.fileCounts
}

// GetFileCounts returns the file counts for the uploader
func (um *UploadManager) GetBacklog() int {
	if um == nil {
		return 0
	}
	return len(um.semaphore)
}

package filetransfer

import (
	"sync"

	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/reflect/protoreflect"

	"github.com/wandb/wandb/nexus/pkg/observability"
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

// FileTransferManager handles the upload/download of files
type FileTransferManager struct {
	// inChan is the channel for incoming messages
	inChan chan *Task

	// fsChan is the channel for messages outgoing to the filestream
	fsChan chan protoreflect.ProtoMessage

	// fileTransfer is the uploader/downloader
	// todo: make this a map of uploaders for different destination storage types
	fileTransfer FileTransfer

	// semaphore is the semaphore for limiting concurrency
	semaphore chan struct{}

	// fileCounts is the file counts for the file transfer
	fileCounts *service.FileCounts

	// fileCountsChan is the channel used to count files uploaded/downloaded by type
	fileCountsChan chan FileType

	// wgfc is the wait group for the file counts channel ops
	wgfc *sync.WaitGroup

	// settings is the settings for the file transfer
	settings *service.Settings

	// logger is the logger for the file transfer
	logger *observability.NexusLogger

	// wg is the wait group
	wg *sync.WaitGroup
}

type FileTransferManagerOption func(fm *FileTransferManager)

func WithLogger(logger *observability.NexusLogger) FileTransferManagerOption {
	return func(fm *FileTransferManager) {
		fm.logger = logger
	}
}

func WithSettings(settings *service.Settings) FileTransferManagerOption {
	return func(fm *FileTransferManager) {
		fm.settings = settings
	}
}

func WithFileTransfer(fileTransfer FileTransfer) FileTransferManagerOption {
	return func(fm *FileTransferManager) {
		fm.fileTransfer = fileTransfer
	}
}

func WithFSCChan(fsChan chan protoreflect.ProtoMessage) FileTransferManagerOption {
	return func(fm *FileTransferManager) {
		fm.fsChan = fsChan
	}
}

func NewFileTransferManager(opts ...FileTransferManagerOption) *FileTransferManager {

	fm := FileTransferManager{
		inChan:         make(chan *Task, bufferSize),
		fileCounts:     &service.FileCounts{},
		fileCountsChan: make(chan FileType, bufferSize),
		wgfc:           &sync.WaitGroup{},
		wg:             &sync.WaitGroup{},
		semaphore:      make(chan struct{}, defaultConcurrencyLimit),
	}

	for _, opt := range opts {
		opt(&fm)
	}

	fm.wgfc.Add(1)
	go fm.fileCount()

	return &fm
}

func (fm *FileTransferManager) fileCount() {
	for fileType := range fm.fileCountsChan {
		switch fileType {
		case WandbFile:
			fm.fileCounts.WandbCount++
		case MediaFile:
			fm.fileCounts.MediaCount++
		case ArtifactFile:
			fm.fileCounts.ArtifactCount++
		default:
			fm.fileCounts.OtherCount++
		}
	}
	fm.wgfc.Done()
}

// Start is the main loop for the fileTransfer
func (fm *FileTransferManager) Start() {
	fm.wg.Add(1)
	go func() {
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

// AddTask adds a task to the fileTransfer
func (fm *FileTransferManager) AddTask(task *Task) {
	fm.logger.Debug("fileTransfer: adding upload task", "path", task.Path, "url", task.Url)
	fm.inChan <- task
}

// FileStreamCallback returns a callback for filestream updates
func (fm *FileTransferManager) FileStreamCallback() func(task *Task) {
	return func(task *Task) {
		fm.logger.Debug("uploader: filestream callback", "task", task)
		if task.Err != nil {
			return
		}
		record := &service.FilesUploaded{
			Files: []string{task.Name},
		}
		fm.fsChan <- record
	}
}

func (um *FileTransferManager) ProgressCallback() func(task *Task) {
	return func(task *Task) {
		if task.Err == nil {
			um.fileCountsChan <- task.FileType
		}
		um.logger.Debug("uploader: progress callback")
	}
}

// Close closes the fileTransfer
func (fm *FileTransferManager) Close() {
	if fm == nil {
		return
	}
	fm.logger.Debug("fileTransfer: Close")
	if fm.inChan == nil {
		return
	}
	// todo: review this, we don't want to cause a panic
	close(fm.inChan)
	fm.wg.Wait()
	close(fm.fileCountsChan)
	fm.wgfc.Wait()
}

// transfer uploads/downloads a file to/from the server
func (fm *FileTransferManager) transfer(task *Task) error {
	var err error
	switch task.TaskType {
	case UploadTask:
		err = fm.fileTransfer.Upload(task)
	case DownloadTask:
		err = fm.fileTransfer.Download(task)
	default:
		fm.logger.CaptureFatalAndPanic("sender: sendRecord: nil RecordType", err)
	}
	return err
}

// GetFileCounts returns the file counts for the fileTransfer
func (fm *FileTransferManager) GetFileCounts() *service.FileCounts {
	if fm == nil {
		return &service.FileCounts{}
	}
	return fm.fileCounts
}

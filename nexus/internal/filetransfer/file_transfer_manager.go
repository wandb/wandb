package filetransfer

import (
	"os"
	"path"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/service"

	"github.com/wandb/wandb/nexus/pkg/observability"
)

type Storage int

const (
	bufferSize              = 32
	defaultConcurrencyLimit = 128
)

type FileTransfer interface {
	Upload(task *UploadTask) error
	Download(task *DownloadTask) error
}

// FileTransferManager handles the upload/download of files
type FileTransferManager struct {
	// inChan is the channel for incoming messages
	inChan chan interface{}

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

func NewFileTransferManager(opts ...FileTransferManagerOption) *FileTransferManager {

	fm := FileTransferManager{
		inChan:         make(chan interface{}, bufferSize),
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
			go func(task interface{}) {
				// Acquire the semaphore
				fm.semaphore <- struct{}{}
				switch t := task.(type) {
				case *UploadTask:
					t.Err = fm.transfer(t)
					// Release the semaphore
					<-fm.semaphore
					if t.Err != nil {
						fm.logger.CaptureError(
							"filetransfer: uploader: error uploading",
							t.Err,
							"path", t.Path, "url", t.Url,
						)
					}
					// Execute the callback.
					if t.CompletionCallback != nil {
						t.CompletionCallback(t)
					}

					if t.Err == nil {
						fm.fileCountsChan <- t.FileType
					}
				case *DownloadTask:
					t.Err = fm.transfer(t)
					// Release the semaphore
					<-fm.semaphore
					if t.Err != nil {
						fm.logger.CaptureError(
							"filetransfer: downloader: error downloading",
							t.Err,
							"path", t.Path, "url", t.Url,
						)
					}
					// Execute the callback.
					if t.CompletionCallback != nil {
						t.CompletionCallback(t)
					}

					if t.Err == nil {
						fm.fileCountsChan <- t.FileType
					}
				default:
					fm.logger.Debug("fileTransfer: go routine for transfer task: invalid task type", "type", t)
				}
				// mark the task as done
				fm.wg.Done()
			}(task)
		}
		fm.wg.Done()
	}()
}

// AddTask adds a task to the fileTransfer
func (fm *FileTransferManager) AddTask(task interface{}) {
	switch t := task.(type) {
	case *UploadTask:
		fm.logger.Debug("fileTransfer: adding upload task", "path", t.Path, "url", t.Url)
		fm.inChan <- t
	case *DownloadTask:
		fm.logger.Debug("fileTransfer: adding download task", "path", t.Path, "url", t.Url)
		fm.inChan <- t
	default:
		fm.logger.Debug("fileTransfer: adding task: invalid task type", "type", t)
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
func (fm *FileTransferManager) transfer(task interface{}) error {
	var err error
	switch t := task.(type) {
	case *UploadTask:
		err = fm.fileTransfer.Upload(t)
	case *DownloadTask:
		// Skip downloading the file if it already exists
		if _, err := os.Stat(t.Path); err == nil {
			return nil
		}
		if err := fm.ensureDownloadRootDir(t.Path); err != nil {
			return err
		}
		err = fm.fileTransfer.Download(t)
	default:
		fm.logger.CaptureFatalAndPanic("sender: sendRecord: nil RecordType", err)
	}
	return err
}

func (fm *FileTransferManager) ensureDownloadRootDir(filePath string) error {
	baseDir := path.Dir(filePath)
	info, err := os.Stat(baseDir)
	if err == nil && info.IsDir() {
		return nil
	}
	return os.MkdirAll(baseDir, 0777)
}

// GetFileCounts returns the file counts for the fileTransfer
func (fm *FileTransferManager) GetFileCounts() *service.FileCounts {
	if fm == nil {
		return &service.FileCounts{}
	}
	return fm.fileCounts
}

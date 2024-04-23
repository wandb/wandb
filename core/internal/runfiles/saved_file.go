package runfiles

import (
	"sync"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/pkg/filestream"
	"github.com/wandb/wandb/core/pkg/observability"
)

// savedFile is a file in the run's files directory.
//
// Not thread-safe.
type savedFile struct {
	fs     filestream.FileStream
	ftm    filetransfer.FileTransferManager
	logger *observability.CoreLogger

	// The path to the actual file.
	realPath string

	// The URL to which the file should be uploaded.
	uploadURL string

	// HTTP headers to set on upload requests for the file.
	uploadHeaders []string

	// The path to the file relative to the run's files directory.
	runPath string

	// The kind of file this is.
	category filetransfer.RunFileKind

	// Wait group for uploads of the file.
	wg *sync.WaitGroup

	// Whether Finish() has been called.
	isFinished bool

	// Whether an upload of the file is currently in-flight.
	isUploading bool

	// Whether the file should be reuploaded after the current upload.
	reuploadScheduled bool
}

func newSavedFile(
	fs filestream.FileStream,
	ftm filetransfer.FileTransferManager,
	logger *observability.CoreLogger,
	realPath string,
	runPath string,
) *savedFile {
	return &savedFile{
		fs:       fs,
		ftm:      ftm,
		logger:   logger,
		realPath: realPath,
		runPath:  runPath,

		wg: &sync.WaitGroup{},
	}
}

func (f *savedFile) SetCategory(category filetransfer.RunFileKind) {
	f.category = category
}

// Upload schedules an upload of savedFile.
//
// If there is an ongoing upload operation for the file, the new upload
// is scheduled to happen after the previous one completes.
func (f *savedFile) Upload(
	url string,
	headers []string,
) {
	if f.uploadURL != "" && f.uploadURL != url {
		f.logger.CaptureError(
			"runfiles: file upload URL changed, but we assumed it wouldn't",
			nil,
			"oldURL", f.uploadURL,
			"newURL", url,
		)
	}

	f.uploadURL = url
	f.uploadHeaders = headers

	if f.isFinished {
		return
	}

	if f.isUploading {
		f.reuploadScheduled = true
		return
	}

	f.doUpload()
}

// doUpload sends an upload Task to the FileTransferManager.
func (f *savedFile) doUpload() {
	task := &filetransfer.Task{
		FileKind: f.category,
		Type:     filetransfer.UploadTask,
		Path:     f.realPath,
		Name:     f.runPath,
		Url:      f.uploadURL,
		Headers:  f.uploadHeaders,
	}

	f.isUploading = true
	f.wg.Add(1)
	task.SetCompletionCallback(f.onFinishUpload)

	f.ftm.AddTask(task)
}

// onFinishUpload marks an upload completed and triggers another if scheduled.
func (f *savedFile) onFinishUpload(task *filetransfer.Task) {
	if task.Err == nil {
		f.fs.SignalFileUploaded(f.runPath)
	}

	f.isUploading = false
	if f.reuploadScheduled {
		f.reuploadScheduled = false
		f.doUpload()
	}

	f.wg.Done()
}

// Finish waits for all scheduled uploads of the file to complete.
func (f *savedFile) Finish() {
	f.isFinished = true
	f.wg.Wait()
}

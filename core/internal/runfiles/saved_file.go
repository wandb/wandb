package runfiles

import (
	"sync"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/pkg/observability"
)

// savedFile is a file in the run's files directory.
type savedFile struct {
	sync.Mutex

	fs     filestream.FileStream
	ftm    filetransfer.FileTransferManager
	logger *observability.CoreLogger

	// The path to the actual file.
	realPath string

	// The path to the file relative to the run's files directory.
	runPath paths.RelativePath

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

	// The URL to which the file should be reuploaded if `reuploadScheduled`.
	reuploadURL string

	// HTTP headers to set on the reupload request for the file if
	// `reuploadScheduled`.
	reuploadHeaders []string
}

func newSavedFile(
	fs filestream.FileStream,
	ftm filetransfer.FileTransferManager,
	logger *observability.CoreLogger,
	realPath string,
	runPath paths.RelativePath,
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
	f.Lock()
	defer f.Unlock()
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
	f.Lock()
	defer f.Unlock()

	if f.isFinished {
		return
	}

	if f.isUploading {
		f.reuploadScheduled = true
		f.reuploadURL = url
		f.reuploadHeaders = headers
		return
	}

	f.doUpload(url, headers)
}

// doUpload sends an upload Task to the FileTransferManager.
//
// It must be called while a lock is held. It temporarily releases the lock.
func (f *savedFile) doUpload(uploadURL string, uploadHeaders []string) {
	task := &filetransfer.DefaultUploadTask{
		FileKind: f.category,
		Path:     f.realPath,
		Name:     string(f.runPath),
		Url:      uploadURL,
		Headers:  uploadHeaders,
	}

	f.isUploading = true
	f.wg.Add(1)
	task.OnComplete = func() { f.onFinishUpload(task) }

	// Temporarily unlock while we run arbitrary code.
	f.Unlock()
	defer f.Lock()
	f.ftm.AddTask(task)
}

// onFinishUpload marks an upload completed and triggers another if scheduled.
func (f *savedFile) onFinishUpload(task *filetransfer.DefaultUploadTask) {
	if task.Err == nil {
		f.fs.StreamUpdate(&filestream.FilesUploadedUpdate{
			RelativePath: string(f.runPath),
		})
	}

	f.Lock()
	f.isUploading = false
	if f.reuploadScheduled {
		f.reuploadScheduled = false
		f.doUpload(f.reuploadURL, f.reuploadHeaders)
	}
	f.Unlock()

	f.wg.Done()
}

// Finish waits for all scheduled uploads of the file to complete.
func (f *savedFile) Finish() {
	f.Lock()
	f.isFinished = true
	f.Unlock()

	f.wg.Wait()
}

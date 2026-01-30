package runfiles

import (
	"context"
	"fmt"
	"path/filepath"
	"sync"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/hashencode"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/wboperation"
)

// savedFile is a file in the run's files directory.
type savedFile struct {
	sync.Mutex

	beforeRunEndCtx context.Context
	fs              filestream.FileStream
	ftm             filetransfer.FileTransferManager
	logger          *observability.CoreLogger
	operations      *wboperation.WandbOperations

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

	// Hash of the last successfully uploaded content (base64 MD5).
	lastUploadedB64MD5 string
}

func newSavedFile(
	beforeRunEndCtx context.Context,
	fs filestream.FileStream,
	ftm filetransfer.FileTransferManager,
	logger *observability.CoreLogger,
	operations *wboperation.WandbOperations,
	realPath string,
	runPath paths.RelativePath,
) *savedFile {
	return &savedFile{
		beforeRunEndCtx: beforeRunEndCtx,
		fs:              fs,
		ftm:             ftm,
		logger:          logger,
		operations:      operations,
		realPath:        realPath,
		runPath:         runPath,

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
// is scheduled to happen after the previous one completes, and only if
// the file bytes differ from the last successful upload.
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
	// Mark as uploading first so concurrent f.Upload calls defer and queue.
	f.isUploading = true

	// Check if the file bytes differ from the last successful upload.
	currentB64MD5, isUnchanged := f.checkContentB64MD5()
	if isUnchanged {
		f.maybeReupload()
		return
	}

	op := f.operations.New(fmt.Sprintf("uploading %s", string(f.runPath)))

	task := &filetransfer.DefaultUploadTask{
		Context:  op.Context(f.beforeRunEndCtx),
		FileKind: f.category,
		Path:     f.realPath,
		Name:     string(f.runPath),
		Url:      uploadURL,
		Headers:  uploadHeaders,
	}

	f.wg.Add(1)
	task.OnComplete = func() {
		op.Finish()
		f.onFinishUpload(task, currentB64MD5)
	}

	// Temporarily unlock while we run arbitrary code.
	f.Unlock()
	defer f.Lock()
	f.ftm.AddTask(task)
}

// checkContentB64MD5 computes the MD5 hash of the file and compares it
// with the hash at the last successful upload.
//
// It must be called while holding the lock, which it temporarily releases.
func (f *savedFile) checkContentB64MD5() (string, bool) {
	f.Unlock()
	currentB64MD5, err := hashencode.ComputeFileB64MD5(f.realPath)
	if err != nil {
		currentB64MD5 = "" // treat file as "changed" below
	}
	f.Lock()
	isUnchanged := currentB64MD5 != "" && f.lastUploadedB64MD5 == currentB64MD5

	return currentB64MD5, isUnchanged
}

// maybeReupload clears the in-flight state and honors any queued reupload.
//
// It must be called while holding the lock.
func (f *savedFile) maybeReupload() {
	f.isUploading = false
	if f.reuploadScheduled {
		f.reuploadScheduled = false
		f.doUpload(f.reuploadURL, f.reuploadHeaders)
	}
}

// onFinishUpload marks an upload completed and triggers another if scheduled.
func (f *savedFile) onFinishUpload(
	task *filetransfer.DefaultUploadTask,
	uploadedB64MD5 string,
) {
	if task.Err == nil {
		f.fs.StreamUpdate(&filestream.FilesUploadedUpdate{
			// Convert backslashes to forward slashes in the file path.
			// Since the backend API requires forward slashes.
			RelativePath: filepath.ToSlash(string(f.runPath)),
		})
		// Record what we believe the server now has.
		f.lastUploadedB64MD5 = uploadedB64MD5
	}

	f.Lock()
	f.maybeReupload()
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

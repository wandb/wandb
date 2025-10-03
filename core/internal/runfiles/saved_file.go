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

	fs         filestream.FileStream
	ftm        filetransfer.FileTransferManager
	logger     *observability.CoreLogger
	operations *wboperation.WandbOperations

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

	// Hash of the file content at the moment the current upload started.
	// Set only while an upload is in-flight.
	uploadingB64MD5 string
}

func newSavedFile(
	fs filestream.FileStream,
	ftm filetransfer.FileTransferManager,
	logger *observability.CoreLogger,
	operations *wboperation.WandbOperations,
	realPath string,
	runPath paths.RelativePath,
) *savedFile {
	return &savedFile{
		fs:         fs,
		ftm:        ftm,
		logger:     logger,
		operations: operations,
		realPath:   realPath,
		runPath:    runPath,

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
// is scheduled to happen after the previous one completes, and the file has changed..
func (f *savedFile) Upload(url string, headers []string) {
	f.Lock()
	if f.shouldDeferUpload(url, headers) {
		f.Unlock()
		return
	}
	// Drop the lock while doing IO.
	f.Unlock()

	currentB64MD5, err := hashencode.ComputeFileB64MD5(f.realPath)
	if err != nil {
		currentB64MD5 = "" // treat as "changed" below
	}

	// Re-acquire and double-check state in case it changed while we hashed.
	f.Lock()
	defer f.Unlock()
	if f.shouldDeferUpload(url, headers) {
		return
	}

	// Check if content unchanged using pre-computed hash.
	if currentB64MD5 != "" && f.lastUploadedB64MD5 == currentB64MD5 {
		return
	}

	f.uploadingB64MD5 = currentB64MD5
	f.doUpload(url, headers)
}

// shouldDeferUpload handles the early-return logic in f.Upload.
//
// Callers must hold f.Lock().
//
// Returns true if the caller should return immediately (either because the
// file is finished, or because an upload is already in-flight, in which case
// a reupload is queued).
func (f *savedFile) shouldDeferUpload(url string, headers []string) bool {
	if f.isFinished {
		return true
	}
	if f.isUploading {
		f.reuploadScheduled = true
		f.reuploadURL = url
		f.reuploadHeaders = headers
		return true
	}
	return false
}

// doUpload sends an upload Task to the FileTransferManager.
//
// It must be called while a lock is held. It temporarily releases the lock.
func (f *savedFile) doUpload(uploadURL string, uploadHeaders []string) {
	op := f.operations.New(fmt.Sprintf("uploading %s", string(f.runPath)))

	task := &filetransfer.DefaultUploadTask{
		Context:  op.Context(context.Background()),
		FileKind: f.category,
		Path:     f.realPath,
		Name:     string(f.runPath),
		Url:      uploadURL,
		Headers:  uploadHeaders,
	}

	f.isUploading = true
	f.wg.Add(1)
	task.OnComplete = func() {
		op.Finish()
		f.onFinishUpload(task)
	}

	// Temporarily unlock while we run arbitrary code.
	f.Unlock()
	defer f.Lock()
	f.ftm.AddTask(task)
}

// onFinishUpload marks an upload completed and triggers another if scheduled.
func (f *savedFile) onFinishUpload(task *filetransfer.DefaultUploadTask) {
	if task.Err == nil {
		f.fs.StreamUpdate(&filestream.FilesUploadedUpdate{
			// Convert backslashes to forward slashes in the file path.
			// Since the backend API requires forward slashes.
			RelativePath: filepath.ToSlash(string(f.runPath)),
		})
	}

	f.Lock()
	defer f.Unlock()

	// Record what we believe the server now has.
	if task.Err == nil {
		if f.uploadingB64MD5 != "" {
			f.lastUploadedB64MD5 = f.uploadingB64MD5
		} else if b64, err := hashencode.ComputeFileB64MD5(f.realPath); err == nil {
			f.lastUploadedB64MD5 = b64
		} else {
			f.lastUploadedB64MD5 = ""
		}
	}

	f.isUploading = false
	if f.reuploadScheduled {
		f.reuploadScheduled = false

		// Unlock temporarily to compute hash.
		f.Unlock()
		currentB64, err := hashencode.ComputeFileB64MD5(f.realPath)
		shouldReupload := (err != nil) || (f.lastUploadedB64MD5 == "") || (currentB64 != f.lastUploadedB64MD5)
		f.uploadingB64MD5 = currentB64
		f.Lock()

		if shouldReupload {
			f.doUpload(f.reuploadURL, f.reuploadHeaders)
		}
	}

	f.wg.Done()
}

// Finish waits for all scheduled uploads of the file to complete.
func (f *savedFile) Finish() {
	f.Lock()
	f.isFinished = true
	f.Unlock()

	f.wg.Wait()
}

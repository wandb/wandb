package runfiles

import (
	"context"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// uploader is the implementation of the Uploader interface.
type uploader struct {
	logger       *observability.CoreLogger
	settings     *settings.Settings
	fileTransfer filetransfer.FileTransferManager
	graphQL      graphql.Client

	// Whether 'Finish' was called.
	isFinished bool

	// Wait group for file uploads.
	uploadWG *sync.WaitGroup

	// Mutex that's locked whenever any state is being read or modified.
	stateMu *sync.Mutex
}

func newUploader(params UploaderParams) *uploader {
	return &uploader{
		logger:       params.Logger,
		settings:     params.Settings,
		fileTransfer: params.FileTransfer,
		graphQL:      params.GraphQL,

		uploadWG: &sync.WaitGroup{},
		stateMu:  &sync.Mutex{},
	}
}

func (u *uploader) Process(record *service.FilesRecord) {
	if !u.lockForOperation("Process") {
		return
	}
	defer u.stateMu.Unlock()

	// Ignore file records in sync mode---we just upload everything at the end.
	if u.settings.Proto.GetXSync().GetValue() {
		return
	}

	nowFiles := make([]string, 0)

	for _, file := range record.GetFiles() {
		switch file.GetPolicy() {
		case service.FilesItem_NOW:
			nowFiles = append(nowFiles, file.GetPath())
		case service.FilesItem_LIVE:
			// TODO
		case service.FilesItem_END:
			// No-op. All files are uploaded at the end by default.
		}
	}

	u.upload(nowFiles)
}

func (u *uploader) UploadNow(path string) {
	if !u.lockForOperation("UploadNow") {
		return
	}
	defer u.stateMu.Unlock()

	u.upload([]string{path})
}

func (u *uploader) UploadRemaining() {
	if !u.lockForOperation("UploadRemaining") {
		return
	}
	defer u.stateMu.Unlock()

	relativePaths := make([]string, 0)
	err := filepath.WalkDir(u.settings.GetFilesDir(),
		func(path string, d fs.DirEntry, err error) error {
			if err != nil {
				return err
			}

			if d.IsDir() {
				return nil
			}

			relativePath, err := filepath.Rel(u.settings.GetFilesDir(), path)
			if err != nil {
				return err
			}

			relativePaths = append(relativePaths, relativePath)
			return nil
		})

	if err != nil {
		// Report the error (e.g. a permissions issue) but try to upload
		// everything we can anyway.
		u.logger.CaptureError(
			"runfiles: error walking run files directory",
			err,
		)
	}

	u.upload(relativePaths)
}

func (u *uploader) Finish() {
	// Update the isFinished state separately. Don't hold mutex while also
	// waiting for the wait group!
	func() {
		u.stateMu.Lock()
		defer u.stateMu.Unlock()

		if u.isFinished {
			return
		}
		u.isFinished = true
	}()

	u.uploadWG.Wait()
}

// Acquires the stateMu mutex if Finish() has not been called.
//
// Returns whether the mutex was locked. If it was locked, the caller
// is responsible for calling Unlock(). Otherwise, the caller must return
// immediately because Finish() has been called.
func (u *uploader) lockForOperation(method string) bool {
	u.stateMu.Lock()

	if u.isFinished {
		u.stateMu.Unlock()

		u.logger.CaptureError(
			fmt.Sprintf("runfiles: called %v() after Finish()", method),
			nil,
		)

		return false
	}

	return true
}

// Uploads the given files unless we are offline.
//
// This increments `uploadWG` and returns immediately. The wait group is
// signalled as file uploads finish.
func (u *uploader) upload(relativePaths []string) {
	if u.settings.IsOffline() {
		return
	}

	relativePaths = u.filterNonExistingAndWarn(relativePaths)
	u.uploadWG.Add(len(relativePaths))

	go func() {
		createRunFilesResponse, err := gql.CreateRunFiles(
			context.Background(),
			u.graphQL,
			u.settings.GetEntity(),
			u.settings.GetProject(),
			u.settings.GetRunID(),
			relativePaths,
		)
		if err != nil {
			u.logger.CaptureError("runfiles: CreateRunFiles returned error", err)
			u.uploadWG.Add(-len(relativePaths))
			return
		}

		if len(createRunFilesResponse.CreateRunFiles.Files) != len(relativePaths) {
			u.logger.CaptureError(
				"runfiles: CreateRunFiles returned unexpected number of files",
				nil,
				"expected",
				len(relativePaths),
				"actual",
				len(createRunFilesResponse.CreateRunFiles.Files),
			)
			u.uploadWG.Add(-len(relativePaths))
			return
		}

		for _, f := range createRunFilesResponse.CreateRunFiles.Files {
			if f.UploadUrl == nil {
				u.logger.CaptureWarn(
					"runfiles: CreateRunFiles has empty UploadUrl",
					"response",
					createRunFilesResponse,
				)
				u.uploadWG.Done()
				continue
			}

			u.scheduleUploadTask(
				f.Name,
				*f.UploadUrl,
				createRunFilesResponse.CreateRunFiles.UploadHeaders,
			)
		}
	}()
}

// Warns for any non-existing files and returns a slice without them.
func (u *uploader) filterNonExistingAndWarn(relativePaths []string) []string {
	existingRelativePaths := make([]string, 0)

	for _, relativePath := range relativePaths {
		localPath := filepath.Join(u.settings.GetFilesDir(), relativePath)

		if _, err := os.Stat(localPath); os.IsNotExist(err) {
			u.logger.Warn("runfiles: upload: file does not exist", "path", localPath)
		} else {
			existingRelativePaths = append(existingRelativePaths, relativePath)
		}
	}

	return existingRelativePaths
}

// Schedules a file upload task.
//
// Decrements `uploadWG` when the task is complete or fails.
func (u *uploader) scheduleUploadTask(
	relativePath string,
	uploadURL string,
	headers []string,
) {
	localPath := filepath.Join(u.settings.GetFilesDir(), relativePath)
	task := &filetransfer.Task{
		Type:    filetransfer.UploadTask,
		Path:    localPath,
		Name:    relativePath,
		Url:     uploadURL,
		Headers: headers,
	}

	// TODO: FileTransferInfoRequest on progress and completion
	task.SetCompletionCallback(func(t *filetransfer.Task) {
		u.uploadWG.Done()
	})

	u.fileTransfer.AddTask(task)
}

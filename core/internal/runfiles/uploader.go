package runfiles

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/filestream"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// uploader is the implementation of the Uploader interface.
type uploader struct {
	ctx           context.Context
	logger        *observability.CoreLogger
	fs            filestream.FileStream
	ftm           filetransfer.FileTransferManager
	settings      *settings.Settings
	graphQL       graphql.Client
	uploadBatcher *uploadBatcher

	// Files in the run's files directory that we know.
	knownFiles map[string]*savedFile

	// Files explicitly requested to be uploaded at the end of the run.
	uploadAtEnd map[string]struct{}

	// Whether 'Finish' was called.
	isFinished bool

	// Wait group for scheduling file uploads.
	uploadWG *sync.WaitGroup

	// Mutex that's locked whenever any state is being read or modified.
	stateMu *sync.Mutex

	// A watcher for 'live' mode files.
	watcher watcher.Watcher
}

func newUploader(params UploaderParams) *uploader {
	uploader := &uploader{
		ctx:      params.Ctx,
		logger:   params.Logger,
		fs:       params.FileStream,
		ftm:      params.FileTransfer,
		settings: params.Settings,
		graphQL:  params.GraphQL,

		knownFiles:  make(map[string]*savedFile),
		uploadAtEnd: make(map[string]struct{}),

		uploadWG: &sync.WaitGroup{},
		stateMu:  &sync.Mutex{},

		watcher: params.FileWatcher,
	}

	uploader.uploadBatcher = newUploadBatcher(
		params.BatchDelay,
		uploader.upload,
	)

	return uploader
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
		u.knownFile(file.GetPath()).
			SetCategory(filetransfer.RunFileKindFromProto(file.GetType()))

		switch file.GetPolicy() {
		case service.FilesItem_NOW:
			nowFiles = append(nowFiles, file.GetPath())

		case service.FilesItem_LIVE:
			// Upload live files both immediately and at the end.
			nowFiles = append(nowFiles, file.GetPath())
			u.uploadAtEnd[file.GetPath()] = struct{}{}

			if err := u.watcher.Watch(u.toRealPath(file.GetPath()), func() {
				u.uploadBatcher.Add([]string{file.GetPath()})
			}); err != nil {
				u.logger.CaptureError(
					"runfiles: error watching file",
					err,
					"file",
					file.GetPath(),
				)
			}

		case service.FilesItem_END:
			u.uploadAtEnd[file.GetPath()] = struct{}{}
		}
	}

	u.uploadBatcher.Add(nowFiles)
}

// toRealPath takes a path relative to the run's files directory and returns
// either an absolute path to that file or a path that's relative to the
// current working directory.
func (u *uploader) toRealPath(path string) string {
	if filepath.IsAbs(path) {
		return path
	}

	return filepath.Join(u.settings.GetFilesDir(), path)
}

func (u *uploader) UploadNow(path string) {
	if !u.lockForOperation("UploadNow") {
		return
	}
	defer u.stateMu.Unlock()

	u.uploadBatcher.Add([]string{path})
}

func (u *uploader) UploadAtEnd(path string) {
	if !u.lockForOperation("UploadAtEnd") {
		return
	}
	defer u.stateMu.Unlock()

	u.uploadAtEnd[path] = struct{}{}
}

func (u *uploader) UploadRemaining() {
	if !u.lockForOperation("UploadRemaining") {
		return
	}
	defer u.stateMu.Unlock()

	relativePaths := make([]string, 0, len(u.uploadAtEnd))
	for k := range u.uploadAtEnd {
		relativePaths = append(relativePaths, k)
	}

	u.uploadBatcher.Add(relativePaths)
}

func (u *uploader) Finish() {
	// Mark as isFinished to prevent new operations.
	u.stateMu.Lock()
	if u.isFinished {
		return
	}
	u.isFinished = true
	u.stateMu.Unlock()

	// Flush any remaining upload batches.
	u.uploadBatcher.Wait()

	// Wait for all upload tasks to get scheduled.
	u.uploadWG.Wait()

	// Wait for all file uploads to complete.
	u.stateMu.Lock()
	defer u.stateMu.Unlock()
	for _, file := range u.knownFiles {
		file.Finish()
	}
}

func (u *uploader) FlushSchedulingForTest() {
	u.uploadBatcher.Wait()
	u.uploadWG.Wait()
}

// knownFile returns a savedFile or creates it if necessary.
func (u *uploader) knownFile(runPath string) *savedFile {
	if u.knownFiles[runPath] == nil {
		u.knownFiles[runPath] = newSavedFile(
			u.fs,
			u.ftm,
			u.logger,
			u.toRealPath(runPath),
			runPath,
		)
	}

	return u.knownFiles[runPath]
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

	u.logger.Debug("runfiles: uploading files", "files", relativePaths)

	relativePaths = u.filterNonExistingAndWarn(relativePaths)
	relativePaths = u.filterIgnored(relativePaths)
	u.uploadWG.Add(len(relativePaths))

	go func() {
		createRunFilesResponse, err := gql.CreateRunFiles(
			u.ctx,
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
		localPath := u.toRealPath(relativePath)

		if _, err := os.Stat(localPath); os.IsNotExist(err) {
			u.logger.Warn("runfiles: upload: file does not exist", "path", localPath)
		} else {
			existingRelativePaths = append(existingRelativePaths, relativePath)
		}
	}

	return existingRelativePaths
}

// Filters any paths that are ignored by the run settings.
func (u *uploader) filterIgnored(relativePaths []string) []string {
	includedPaths := make([]string, 0)

outerLoop:
	for _, relativePath := range relativePaths {
		for _, ignoreGlob := range u.settings.GetIgnoreGlobs() {
			if matched, _ := filepath.Match(ignoreGlob, relativePath); matched {
				continue outerLoop
			}
		}

		includedPaths = append(includedPaths, relativePath)
	}

	return includedPaths
}

// Schedules a file upload task.
//
// Decrements `uploadWG` when the task is complete or fails.
func (u *uploader) scheduleUploadTask(
	relativePath string,
	uploadURL string,
	headers []string,
) {
	u.stateMu.Lock()
	defer u.stateMu.Unlock()

	u.knownFile(relativePath).Upload(uploadURL, headers)
	u.uploadWG.Done()
}

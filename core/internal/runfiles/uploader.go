package runfiles

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/observability"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// uploader is the implementation of the Uploader interface.
type uploader struct {
	extraWork     runwork.ExtraWork
	logger        *observability.CoreLogger
	fs            filestream.FileStream
	ftm           filetransfer.FileTransferManager
	settings      *settings.Settings
	graphQL       graphql.Client
	uploadBatcher *uploadBatcher

	// Files in the run's files directory that we know.
	knownFiles map[paths.RelativePath]*savedFile

	// Files explicitly requested to be uploaded at the end of the run.
	uploadAtEnd map[paths.RelativePath]struct{}

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
		extraWork: params.ExtraWork,
		logger:    params.Logger,
		fs:        params.FileStream,
		ftm:       params.FileTransfer,
		settings:  params.Settings,
		graphQL:   params.GraphQL,

		knownFiles:  make(map[paths.RelativePath]*savedFile),
		uploadAtEnd: make(map[paths.RelativePath]struct{}),

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

func (u *uploader) Process(record *spb.FilesRecord) {
	if err := u.lockForOperation("Process"); err != nil {
		u.logger.CaptureError(err, "record", record)
		return
	}
	defer u.stateMu.Unlock()

	// Ignore file records in sync mode---we just upload everything at the end.
	if u.settings.IsSync() {
		return
	}

	nowFiles := make([]paths.RelativePath, 0)

	for _, file := range record.GetFiles() {
		maybeRunPath, err := paths.Relative(file.GetPath())
		if err != nil {
			u.logger.CaptureError(
				fmt.Errorf(
					"runfiles: file path is not relative: %v",
					err,
				))
			continue
		}
		runPath := *maybeRunPath

		u.knownFile(runPath).
			SetCategory(filetransfer.RunFileKindFromProto(file.GetType()))

		switch file.GetPolicy() {
		case spb.FilesItem_NOW:
			nowFiles = append(nowFiles, runPath)

		case spb.FilesItem_LIVE:
			// Upload live files both immediately and at the end.
			nowFiles = append(nowFiles, runPath)
			u.uploadAtEnd[runPath] = struct{}{}

			if err := u.watcher.Watch(u.toRealPath(string(runPath)), func() {
				u.uploadBatcher.Add([]paths.RelativePath{runPath})
			}); err != nil {
				u.logger.CaptureError(
					fmt.Errorf(
						"runfiles: error watching file: %v",
						err,
					),
					"path", file.GetPath())
			}

		case spb.FilesItem_END:
			u.uploadAtEnd[runPath] = struct{}{}
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

func (u *uploader) UploadNow(path paths.RelativePath) {
	if err := u.lockForOperation("UploadNow"); err != nil {
		u.logger.CaptureError(err, "path", string(path))
		return
	}
	defer u.stateMu.Unlock()

	u.uploadBatcher.Add([]paths.RelativePath{path})
}

func (u *uploader) UploadAtEnd(path paths.RelativePath) {
	if err := u.lockForOperation("UploadAtEnd"); err != nil {
		u.logger.CaptureError(err, "path", string(path))
		return
	}
	defer u.stateMu.Unlock()

	u.uploadAtEnd[path] = struct{}{}
}

func (u *uploader) UploadRemaining() {
	if err := u.lockForOperation("UploadRemaining"); err != nil {
		u.logger.CaptureError(err)
		return
	}
	defer u.stateMu.Unlock()

	runPaths := make([]paths.RelativePath, 0, len(u.uploadAtEnd))
	for k := range u.uploadAtEnd {
		runPaths = append(runPaths, k)
	}

	u.uploadBatcher.Add(runPaths)
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
func (u *uploader) knownFile(runPath paths.RelativePath) *savedFile {
	if u.knownFiles[runPath] == nil {
		u.knownFiles[runPath] = newSavedFile(
			u.fs,
			u.ftm,
			u.logger,
			u.toRealPath(string(runPath)),
			runPath,
		)
	}

	return u.knownFiles[runPath]
}

// Acquires the stateMu mutex if Finish() has not been called.
//
// On success, the mutex is locked and the caller is responsible for
// calling Unlock(). On failure, the mutex is not locked, an error is
// returned, and the caller must return immediately.
func (u *uploader) lockForOperation(method string) error {
	u.stateMu.Lock()

	if u.isFinished {
		u.stateMu.Unlock()

		return fmt.Errorf("runfiles: called %v() after Finish()", method)
	}

	return nil
}

// Uploads the given files unless we are offline.
//
// This increments `uploadWG` and returns immediately. The wait group is
// signalled as file uploads finish.
func (u *uploader) upload(runPaths []paths.RelativePath) {
	if u.settings.IsOffline() {
		return
	}

	u.logger.Debug("runfiles: uploading files", "files", runPaths)

	runPaths = u.filterNonExistingAndWarn(runPaths)
	runPaths = u.filterIgnored(runPaths)
	u.uploadWG.Add(len(runPaths))

	runSlashPaths := make([]string, len(runPaths))
	for i, path := range runPaths {
		runSlashPaths[i] = filepath.ToSlash(string(path))
	}

	go func() {
		createRunFilesResponse, err := gql.CreateRunFiles(
			u.extraWork.BeforeEndCtx(),
			u.graphQL,
			u.settings.GetEntity(),
			u.settings.GetProject(),
			u.settings.GetRunID(),
			runSlashPaths,
		)
		if err != nil {
			u.logger.CaptureError(
				fmt.Errorf("runfiles: CreateRunFiles returned error: %v", err))
			u.uploadWG.Add(-len(runPaths))
			return
		}

		if len(createRunFilesResponse.CreateRunFiles.Files) != len(runPaths) {
			u.logger.CaptureError(
				errors.New(
					"runfiles: CreateRunFiles returned"+
						" unexpected number of files"),
				"actual", len(createRunFilesResponse.CreateRunFiles.Files),
				"expected", len(runPaths),
			)
			u.uploadWG.Add(-len(runPaths))
			return
		}

		for _, f := range createRunFilesResponse.CreateRunFiles.Files {
			if f.UploadUrl == nil {
				u.logger.CaptureWarn(
					"runfiles: CreateRunFiles has empty UploadUrl",
					"response", createRunFilesResponse)
				u.uploadWG.Done()
				continue
			}

			maybeRunPath, err := paths.Relative(filepath.FromSlash(f.Name))
			if err != nil || !maybeRunPath.IsLocal() {
				u.logger.CaptureError(
					fmt.Errorf(
						"runfiles: CreateRunFiles returned unexpected file name: %v",
						err,
					),
					"response", createRunFilesResponse)
				u.uploadWG.Done()
				continue
			}
			runPath := *maybeRunPath

			u.scheduleUploadTask(
				runPath,
				*f.UploadUrl,
				createRunFilesResponse.CreateRunFiles.UploadHeaders,
			)
		}
	}()
}

// Warns for any non-existing files and returns a slice without them.
func (u *uploader) filterNonExistingAndWarn(
	runPaths []paths.RelativePath,
) []paths.RelativePath {
	existingPaths := make([]paths.RelativePath, 0)

	for _, runPath := range runPaths {
		realPath := u.toRealPath(string(runPath))

		if _, err := os.Stat(realPath); os.IsNotExist(err) {
			u.logger.Warn("runfiles: upload: file does not exist", "path", realPath)
		} else {
			existingPaths = append(existingPaths, runPath)
		}
	}

	return existingPaths
}

// Filters any paths that are ignored by the run settings.
func (u *uploader) filterIgnored(
	runPaths []paths.RelativePath,
) []paths.RelativePath {
	includedPaths := make([]paths.RelativePath, 0)

outerLoop:
	for _, runPath := range runPaths {
		for _, ignoreGlob := range u.settings.GetIgnoreGlobs() {
			if matched, _ := filepath.Match(ignoreGlob, string(runPath)); matched {
				continue outerLoop
			}
		}

		includedPaths = append(includedPaths, runPath)
	}

	return includedPaths
}

// Schedules a file upload task.
//
// Decrements `uploadWG` when the task is complete or fails.
func (u *uploader) scheduleUploadTask(
	runPath paths.RelativePath,
	uploadURL string,
	headers []string,
) {
	u.stateMu.Lock()
	defer u.stateMu.Unlock()

	u.knownFile(runPath).Upload(uploadURL, headers)
	u.uploadWG.Done()
}

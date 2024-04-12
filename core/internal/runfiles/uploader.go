package runfiles

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/radovskyb/watcher"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/filestream"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"golang.org/x/sync/errgroup"
)

const (
	filePollingPeriod = 500 * time.Millisecond
)

// uploader is the implementation of the Uploader interface.
type uploader struct {
	ctx               context.Context
	logger            *observability.CoreLogger
	settings          *settings.Settings
	fileStream        filestream.FileStream
	debouncedTransfer *debouncedTransfer
	graphQL           graphql.Client
	uploadBatcher     *uploadBatcher

	// A mapping from files to their category, if set.
	//
	// The default category is OTHER. The keys are paths relative to
	// the files directory.
	category map[string]filetransfer.RunFileKind

	// Files explicitly requested to be uploaded at the end of the run.
	uploadAtEnd map[string]struct{}

	// Whether 'Finish' was called.
	isFinished bool

	// Wait group for file uploads.
	uploadWG *sync.WaitGroup

	// Mutex that's locked whenever any state is being read or modified.
	stateMu *sync.Mutex

	// A watcher for 'live' mode files.
	watcherOrNil *watcher.Watcher

	// Wait group for the watcher.
	watcherWG *sync.WaitGroup
}

func newUploader(params UploaderParams) *uploader {
	uploader := &uploader{
		ctx:        params.Ctx,
		logger:     params.Logger,
		settings:   params.Settings,
		fileStream: params.FileStream,
		debouncedTransfer: newDebouncedTransfer(
			params.FileTransfer,
			params.Logger,
		),
		graphQL: params.GraphQL,

		category:    make(map[string]filetransfer.RunFileKind),
		uploadAtEnd: make(map[string]struct{}),

		uploadWG: &sync.WaitGroup{},
		stateMu:  &sync.Mutex{},

		watcherWG: &sync.WaitGroup{},
	}

	if params.BatchWindow != 0 {
		params.BatchDelayFunc = func() <-chan struct{} {
			ch := make(chan struct{})
			go func() {
				<-time.After(params.BatchWindow)
				ch <- struct{}{}
			}()
			return ch
		}
	}

	uploader.uploadBatcher = newUploadBatcher(
		params.BatchDelayFunc,
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
		u.category[file.GetPath()] =
			filetransfer.RunFileKindFromProto(file.GetType())

		switch file.GetPolicy() {
		case service.FilesItem_NOW:
			nowFiles = append(nowFiles, file.GetPath())

		case service.FilesItem_LIVE:
			// Upload live files both immediately and at the end.
			nowFiles = append(nowFiles, file.GetPath())
			u.uploadAtEnd[file.GetPath()] = struct{}{}

			if err := u.watch(file.GetPath()); err != nil {
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

func (u *uploader) SetCategory(path string, category filetransfer.RunFileKind) {
	if !u.lockForOperation("SetCategory") {
		return
	}
	defer u.stateMu.Unlock()

	u.category[path] = category
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

	u.uploadBatcher.Finish()
	u.uploadWG.Wait()

	if u.watcherOrNil != nil {
		u.watcherOrNil.Close()
		u.watcherWG.Wait()
	}
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

// Begins watching the given path and uploading when the file changes.
func (u *uploader) watch(path string) error {
	// Lazily start the watcher when we receive our first file to watch.
	if u.watcherOrNil == nil {
		if err := u.startWatcher(); err != nil {
			return err
		}
	}

	if err := u.watcherOrNil.Add(path); err != nil {
		return err
	}

	return nil
}

// Starts up the file watcher goroutine.
func (u *uploader) startWatcher() error {
	if u.watcherOrNil != nil {
		return fmt.Errorf(
			"runfiles: tried to start watcher, but it is already started",
		)
	}

	u.watcherOrNil = watcher.New()
	u.watcherOrNil.FilterOps(watcher.Write)

	grp, ctx := errgroup.WithContext(u.ctx)
	u.watcherWG.Add(2)

	grp.Go(func() error {
		defer u.watcherWG.Done()

		u.loopWatchFiles(ctx)

		return nil
	})

	grp.Go(func() error {
		defer u.watcherWG.Done()

		if err := u.watcherOrNil.Start(filePollingPeriod); err != nil {
			u.logger.CaptureError(
				"runfiles: failed to start file watcher",
				err,
			)

			// Returning the error cancels the above loop.
			return err
		}

		return nil
	})

	// We want to guarantee at this point that either:
	//   1. Watcher.Start() is successfully looping
	//   2. Watcher.Start() returned an error
	// Until this, Watcher.Close() is a no-op! If Finish() is called too
	// quickly, it will get stuck waiting on watcherWG because Watcher.Close()
	// wouldn't have stopped the above goroutines.
	watcherStarted := make(chan struct{})
	go func() {
		u.watcherOrNil.Wait()
		watcherStarted <- struct{}{}
	}()
	select {
	case <-watcherStarted:
	case <-ctx.Done():
	}

	return nil
}

// Loops and processes file events.
//
// 'ctx' is used to break the loop in case the watcher fails to even
// start, in which case none of its channels will ever receive a message.
func (u *uploader) loopWatchFiles(ctx context.Context) {
	for {
		select {
		case event := <-u.watcherOrNil.Event:
			if event.Op != watcher.Write {
				continue
			}
			u.UploadNow(event.Path)

		case err := <-u.watcherOrNil.Error:
			u.logger.CaptureError(
				"runfiles: error in file watcher",
				err,
			)

		case <-u.watcherOrNil.Closed:
			return

		case <-ctx.Done():
			return
		}
	}
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
		localPath := filepath.Join(u.settings.GetFilesDir(), relativePath)

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

	localPath := filepath.Join(u.settings.GetFilesDir(), relativePath)
	task := &filetransfer.Task{
		FileKind: u.category[relativePath],
		Type:     filetransfer.UploadTask,
		Path:     localPath,
		Name:     relativePath,
		Url:      uploadURL,
		Headers:  headers,
	}

	task.SetCompletionCallback(func(t *filetransfer.Task) {
		if t.Err == nil {
			u.fileStream.SignalFileUploaded(t.Name)
		}

		u.uploadWG.Done()
	})

	u.debouncedTransfer.AddTask(task)
}

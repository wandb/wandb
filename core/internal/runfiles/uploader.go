package runfiles

import (
	"fmt"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filetransfer"
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
	uploadWg *sync.WaitGroup

	// Mutex that's locked whenever any state is being read or modified.
	stateMu *sync.Mutex
}

func newUploader(params UploaderParams) *uploader {
	return &uploader{
		logger:       params.Logger,
		settings:     params.Settings,
		fileTransfer: params.FileTransfer,
		graphQL:      params.GraphQL,

		uploadWg: &sync.WaitGroup{},
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

	// TODO
}

func (u *uploader) UploadNow(path string) {
	if !u.lockForOperation("UploadNow") {
		return
	}
	defer u.stateMu.Unlock()

	u.upload(path)
}

func (u *uploader) UploadRemaining() {
	if !u.lockForOperation("UploadRemaining") {
		return
	}
	defer u.stateMu.Unlock()

	// TODO
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

	u.uploadWg.Wait()
}

// Schedules a file upload task, unless we are offline.
func (u *uploader) upload(path string) {
	if u.settings.IsOffline() {
		return
	}

	// TODO
	_ = path
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

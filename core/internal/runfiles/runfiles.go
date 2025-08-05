// Package runfiles deals with the saved files of a W&B run.
//
// This includes files saved via `wandb.save(...)` and internally created
// files. It's separate from "artifacts", which is a newer model and exists
// in parallel to this.
package runfiles

import (
	"github.com/Khan/genqlient/graphql"
	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// UploaderProviders binds UploaderFactory.
var UploaderProviders = wire.NewSet(
	wire.Struct(new(UploaderFactory), "*"),
)

// Uploader uploads the files in a run's files directory.
type Uploader interface {
	// Process handles a file save record from a client.
	Process(record *spb.FilesRecord)

	// UploadNow asynchronously uploads a run file.
	//
	// The path is relative to the run's file directory.
	UploadNow(path paths.RelativePath, category filetransfer.RunFileKind)

	// UploadAtEnd marks a file to be uploaded at the end of the run.
	//
	// The path is relative to the run's file directory.
	UploadAtEnd(path paths.RelativePath, category filetransfer.RunFileKind)

	// UploadRemaining asynchronously uploads all files that should be
	// uploaded at the end of the run.
	UploadRemaining()

	// Finish waits for all asynchronous operations to finish.
	//
	// After this, no other methods may be called.
	Finish()
}

// UploaderTesting has additional test-only Uploader methods.
type UploaderTesting interface {
	// FlushSchedulingForTest blocks until all requested uploads are scheduled.
	//
	// If no more Process / Upload methods are invoked and no upload tasks
	// complete after this method, then no more upload tasks will be created.
	FlushSchedulingForTest()
}

// UploaderFactory constructs Uploader instances.
type UploaderFactory struct {
	ExtraWork    runwork.ExtraWork
	FileTransfer filetransfer.FileTransferManager
	FileWatcher  watcher.Watcher
	GraphQL      graphql.Client
	Logger       *observability.CoreLogger
	Operations   *wboperation.WandbOperations
	Settings     *settings.Settings
}

// New returns a new Uploader.
//
// batchDelay is how long to wait to batch upload operations. Uploads scheduled
// within this duration of each other are combined into a single GraphQL call.
func (f *UploaderFactory) New(
	batchDelay waiting.Delay,
	fileStream filestream.FileStream,
) Uploader {
	return newUploader(f, batchDelay, fileStream)
}

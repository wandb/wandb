// Package runfiles deals with the saved files of a W&B run.
//
// This includes files saved via `wandb.save(...)` and internally created
// files. It's separate from "artifacts", which is a newer model and exists
// in parallel to this.
package runfiles

import (
	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Uploader uploads the files in a run's files directory.
type Uploader interface {
	// Process handles a file save record from a client.
	Process(record *spb.FilesRecord)

	// UploadNow asynchronously uploads a run file.
	//
	// The path is relative to the run's file directory.
	UploadNow(path paths.RelativePath)

	// UploadAtEnd marks a file to be uploaded at the end of the run.
	//
	// The path is relative to the run's file directory.
	UploadAtEnd(path paths.RelativePath)

	// UploadRemaining asynchronously uploads all files that should be
	// uploaded at the end of the run.
	UploadRemaining()

	// Finish waits for all asynchronous operations to finish.
	//
	// After this, no other methods may be called.
	Finish()
}

func NewUploader(params UploaderParams) Uploader {
	return newUploader(params)
}

// UploaderTesting has additional test-only Uploader methods.
type UploaderTesting interface {
	// FlushSchedulingForTest blocks until all requested uploads are scheduled.
	//
	// If no more Process / Upload methods are invoked and no upload tasks
	// complete after this method, then no more upload tasks will be created.
	FlushSchedulingForTest()
}

type UploaderParams struct {
	ExtraWork    runwork.ExtraWork
	Logger       *observability.CoreLogger
	Settings     *settings.Settings
	FileStream   filestream.FileStream
	FileTransfer filetransfer.FileTransferManager
	GraphQL      graphql.Client
	FileWatcher  watcher.Watcher

	// How long to wait to batch upload operations.
	//
	// This helps if multiple uploads are scheduled around the same time by
	// grouping those that fall within this duration of each other and reducing
	// the number of GraphQL invocations.
	BatchDelay waiting.Delay
}

// Package runfiles deals with the saved files of a W&B run.
//
// This includes files saved via `wandb.save(...)` and internally created
// files. It's separate from "artifacts", which is a newer model and exists
// in parallel to this.
package runfiles

import (
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// Uploader uploads the files in a run's files directory.
type Uploader interface {
	// Process handles a file save record from a client.
	Process(record *service.FilesRecord)

	// Sets a file's category for statistics reporting.
	//
	// The path is relative to the run's file directory.
	SetCategory(path string, category filetransfer.RunFileKind)

	// UploadNow asynchronously uploads a run file.
	//
	// The path is relative to the run's file directory.
	UploadNow(path string)

	// UploadAtEnd marks a file to be uploaded at the end of the run.
	//
	// The path is relative to the run's file directory.
	UploadAtEnd(path string)

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

type UploaderParams struct {
	Logger       *observability.CoreLogger
	Settings     *settings.Settings
	FileTransfer filetransfer.FileTransferManager
	GraphQL      graphql.Client

	// How long to wait to batch upload operations.
	//
	// This helps if multiple uploads are scheduled around the same time by
	// grouping those that fall within this duration of each other and reducing
	// the number of GraphQL invocations.
	BatchWindow time.Duration

	// Alternative to BatchWindow that specifies a waiting function.
	BatchDelayFunc func() <-chan struct{}
}

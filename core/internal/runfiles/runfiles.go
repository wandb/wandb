// Package runfiles deals with the saved files of a W&B run.
//
// This includes files saved via `wandb.save(...)` and internally created
// files. It's separate from "artifacts", which is a newer model and exists
// in parallel to this.
package runfiles

import (
	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// FilesRecordHandler processes FilesRecords from the client.
type FilesRecordHandler interface {
	// Asynchronously handles a file save record from a client.
	ProcessRecord(record *service.FilesRecord)

	// Asynchronously uploads all remaining files.
	Flush()

	// Waits for all async operations to finish.
	//
	// This must be called after all other method invocations return.
	// Afteward, no more methods may be called.
	Finish()
}

type FilesRecordHandlerParams struct {
	Logger       *observability.CoreLogger
	Settings     *settings.Settings
	FileTransfer filetransfer.FileTransferManager
	GraphQL      graphql.Client
}

func New(params FilesRecordHandlerParams) FilesRecordHandler {
	return newFilesRecordHandler(params)
}

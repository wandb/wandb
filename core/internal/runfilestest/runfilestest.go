package runfilestest

import (
	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filestreamtest"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/filetransfertest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/internal/watchertest"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Params for constructing a runfiles.Uploader for testing.
type Params struct {
	ExtraWork    runwork.ExtraWork
	FileTransfer filetransfer.FileTransferManager
	FileWatcher  watcher.Watcher
	GraphQL      graphql.Client
	Logger       *observability.CoreLogger
	Operations   *wboperation.WandbOperations
	Settings     *settings.Settings

	BatchDelay waiting.Delay
	FileStream filestream.FileStream
}

// WithTestDefaults constructs an uploader with reasonable test defaults.
//
// The given factory does not need to have all fields set.
func WithTestDefaults(params Params) runfiles.Uploader {
	if params.ExtraWork == nil {
		params.ExtraWork = runworktest.New()
	}

	if params.Logger == nil {
		params.Logger = observability.NewNoOpLogger()
	}

	if params.Settings == nil {
		params.Settings = settings.From(&spb.Settings{})
	}

	if params.FileStream == nil {
		params.FileStream = filestreamtest.NewFakeFileStream()
	}

	if params.FileTransfer == nil {
		params.FileTransfer = filetransfertest.NewFakeFileTransferManager()
	}

	if params.GraphQL == nil {
		params.GraphQL = gqlmock.NewMockClient()
	}

	if params.FileWatcher == nil {
		params.FileWatcher = watchertest.NewFakeWatcher()
	}

	factory := &runfiles.UploaderFactory{
		ExtraWork:    params.ExtraWork,
		FileTransfer: params.FileTransfer,
		FileWatcher:  params.FileWatcher,
		GraphQL:      params.GraphQL,
		Logger:       params.Logger,
		Operations:   params.Operations,
		Settings:     params.Settings,
	}

	return factory.New(params.BatchDelay, params.FileStream)
}

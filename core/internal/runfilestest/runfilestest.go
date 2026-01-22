package runfilestest

import (
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filestreamtest"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/filetransfertest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runupsertertest"
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
	FileTransfer filetransfer.FileTransferManager
	FileWatcher  watcher.Watcher
	GraphQL      graphql.Client
	Logger       *observability.CoreLogger
	Operations   *wboperation.WandbOperations
	RunHandle    *runhandle.RunHandle
	Settings     *settings.Settings

	BatchDelay waiting.Delay
	ExtraWork  runwork.ExtraWork
	FileStream filestream.FileStream
}

// WithTestDefaults constructs an uploader with reasonable test defaults.
//
// The given factory does not need to have all fields set.
func WithTestDefaults(t *testing.T, params Params) runfiles.Uploader {
	t.Helper()

	if params.ExtraWork == nil {
		params.ExtraWork = runworktest.New()
	}

	if params.Logger == nil {
		params.Logger = observability.NewNoOpLogger()
	}

	if params.Settings == nil {
		params.Settings = settings.From(&spb.Settings{})
	}

	if params.RunHandle == nil {
		params.RunHandle = runhandle.New()
		err := params.RunHandle.Init(runupsertertest.NewOfflineUpserter(t))
		require.NoError(t, err)
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
		FileTransfer: params.FileTransfer,
		FileWatcher:  params.FileWatcher,
		GraphQL:      params.GraphQL,
		Logger:       params.Logger,
		Operations:   params.Operations,
		RunHandle:    params.RunHandle,
		Settings:     params.Settings,
	}

	return factory.New(params.BatchDelay, params.ExtraWork, params.FileStream)
}

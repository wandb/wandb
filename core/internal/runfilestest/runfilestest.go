package runfilestest

import (
	"github.com/wandb/wandb/core/internal/filestreamtest"
	"github.com/wandb/wandb/core/internal/filetransfertest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/watchertest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Sets nice default parameters for testing purposes.
func WithTestDefaults(params runfiles.UploaderParams) runfiles.UploaderParams {
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

	return params
}

package runfilestest

import (
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/watcher2test"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// Sets nice default parameters for testing purposes.
func WithTestDefaults(params runfiles.UploaderParams) runfiles.UploaderParams {
	if params.Logger == nil {
		params.Logger = observability.NewNoOpLogger()
	}

	if params.Settings == nil {
		params.Settings = settings.From(&service.Settings{})
	}

	if params.FileWatcher == nil {
		params.FileWatcher = watcher2test.NewFakeWatcher()
	}

	return params
}

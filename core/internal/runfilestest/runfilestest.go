package runfilestest

import (
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/watchertest"
	"github.com/wandb/wandb/core/pkg/observability"
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

	if params.FileWatcher == nil {
		params.FileWatcher = watchertest.NewFakeWatcher()
	}

	return params
}

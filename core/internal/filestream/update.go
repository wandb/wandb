package filestream

import (
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/observability"
)

// Update is a modification to the filestream's next API request.
type Update interface {
	// Apply processes data and modifies the next API request.
	Apply(UpdateContext) error
}

type UpdateContext struct {
	// MakeRequest queues a filestream API request.
	MakeRequest func(*FileStreamRequest)

	Settings *settings.Settings

	Logger  *observability.CoreLogger
	Printer *observability.Printer
}

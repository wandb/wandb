package filestream

import (
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// Update is a modification to the filestream's next API request.
type Update interface {
	// Apply processes data and modifies the next API request.
	Apply(UpdateContext) error
}

type UpdateContext struct {
	// MakeRequest queues a filestream API request.
	MakeRequest func(*FileStreamRequest)

	Settings *service.Settings

	Logger  *observability.CoreLogger
	Printer *observability.Printer
}

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

type BufferMutation func(*FileStreamRequestBuffer)

type UpdateContext struct {
	// ModifyRequest modifies the filestream's buffered data.
	//
	// The state update runs in a separate goroutine.
	Modify func(BufferMutation)

	Settings *service.Settings

	Logger  *observability.CoreLogger
	Printer *observability.Printer
}

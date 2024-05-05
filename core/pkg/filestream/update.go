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
	// ModifyRequest updates the next filestream API request.
	//
	// The state update runs in a separate goroutine.
	ModifyRequest func(CollectorStateUpdate)

	Settings *service.Settings
	ClientID string

	Logger  *observability.CoreLogger
	Printer *observability.Printer
}

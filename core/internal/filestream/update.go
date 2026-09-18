package filestream

import (
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runencodestats"
	"github.com/wandb/wandb/core/internal/settings"
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

	// EncodeStats accumulates the cost of encoding history.
	//
	// It may be nil, in which case nothing is recorded.
	EncodeStats *runencodestats.Stats
}

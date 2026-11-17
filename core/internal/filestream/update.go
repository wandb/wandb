package filestream

import (
	"github.com/wandb/wandb/core/internal/filestreamstats"
	"github.com/wandb/wandb/core/internal/observability"
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

	// UseProto is fixed for the stream by the TYPED_SYSTEM_METRICS feature.
	UseProto bool

	Logger  *observability.CoreLogger
	Printer *observability.Printer

	Stats *filestreamstats.Stats
}

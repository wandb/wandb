package filestream

import (
	"github.com/wandb/wandb/core/internal/runsummary"
)

// SummaryUpdate contains updates to a run's summary.
type SummaryUpdate struct {
	Updates *runsummary.Updates
}

func (u *SummaryUpdate) Apply(ctx UpdateContext) error {
	ctx.MakeRequest(&FileStreamRequest{SummaryUpdates: u.Updates})
	return nil
}

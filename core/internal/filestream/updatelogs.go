package filestream

import (
	"github.com/wandb/wandb/core/internal/collections"
)

// LogsUpdate is new lines in a run's console output.
type LogsUpdate struct {
	Lines collections.SparseList[string]
}

func (u *LogsUpdate) Apply(ctx UpdateContext) error {
	ctx.MakeRequest(&FileStreamRequest{
		ConsoleLines: u.Lines,
	})

	return nil
}

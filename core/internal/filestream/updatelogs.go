package filestream

import "github.com/wandb/wandb/core/internal/sparselist"

// LogsUpdate is new lines in a run's console output.
type LogsUpdate struct {
	Lines sparselist.SparseList[string]
}

func (u *LogsUpdate) Apply(ctx UpdateContext) error {
	ctx.MakeRequest(&FileStreamRequest{
		ConsoleLines: u.Lines,
	})

	return nil
}

package filestream

import "github.com/wandb/wandb/core/internal/sparselist"

// LogsUpdate is new lines in a run's console output.
type LogsUpdate struct {
	Lines sparselist.SparseList[string]
}

func (u *LogsUpdate) Apply(ctx UpdateContext) error {
	ctx.Modify(func(buffer *FileStreamRequestBuffer) {
		buffer.ConsoleLogUpdates.Update(u.Lines)
	})

	return nil
}

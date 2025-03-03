package filestream

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/sparselist"
)

// LogsUpdate is new lines in a run's console output.
type LogsUpdate struct {
	Lines sparselist.SparseList[string]
}

func (u *LogsUpdate) Apply(ctx UpdateContext) error {
	fmt.Println("filestream: LogsUpdate", u.Lines)
	ctx.MakeRequest(&FileStreamRequest{
		ConsoleLines: u.Lines,
	})

	return nil
}

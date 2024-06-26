package filestream

import "github.com/wandb/wandb/core/internal/sparselist"

// LogsUpdate is new lines in a run's console output.
type LogsUpdate struct {
	Lines sparselist.SparseList[string]
}

func (u *LogsUpdate) Apply(ctx UpdateContext) error {
	ctx.ModifyRequest(&collectorLogsUpdate{lines: u.Lines})

	return nil
}

type collectorLogsUpdate struct {
	lines sparselist.SparseList[string]
}

func (u *collectorLogsUpdate) Apply(state *CollectorState) {
	state.ConsoleLogUpdates.Update(u.lines)
}

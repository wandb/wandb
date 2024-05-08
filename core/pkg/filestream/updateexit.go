package filestream

import "github.com/wandb/wandb/core/pkg/service"

// ExitUpdate contains the run's script's exit code.
type ExitUpdate struct {
	Record *service.RunExitRecord
}

func (u *ExitUpdate) Apply(ctx UpdateContext) error {

	ctx.ModifyRequest(&collectorExitUpdate{
		exitCode: u.Record.ExitCode,
	})

	return nil
}

type collectorExitUpdate struct {
	exitCode int32
}

func (u *collectorExitUpdate) Apply(state *CollectorState) {
	boolTrue := true

	state.ExitCode = &u.exitCode
	state.Complete = &boolTrue
}

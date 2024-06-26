package filestream

import "github.com/wandb/wandb/core/pkg/service"

// ExitUpdate contains the run's script's exit code.
type ExitUpdate struct {
	Record *service.RunExitRecord
}

func (u *ExitUpdate) Apply(ctx UpdateContext) error {
	exitCode := u.Record.ExitCode
	complete := true

	ctx.Modify(func(buffer *FileStreamRequestBuffer) {
		buffer.ExitCode = &exitCode
		buffer.Complete = &complete
	})

	return nil
}

package filestream

import "github.com/wandb/wandb/core/pkg/service"

// ExitUpdate contains the run's script's exit code.
type ExitUpdate struct {
	Record *service.RunExitRecord
}

func (u *ExitUpdate) Chunk(fs *fileStream) error {
	boolTrue := true

	fs.addTransmit(processedChunk{
		Complete: &boolTrue,
		Exitcode: &u.Record.ExitCode,
	})

	return nil
}

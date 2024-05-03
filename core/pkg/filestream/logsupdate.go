package filestream

import "github.com/wandb/wandb/core/pkg/service"

// LogsUpdate is new lines in a run's console output.
type LogsUpdate struct {
	Record *service.OutputRawRecord
}

func (u *LogsUpdate) Chunk(fs *fileStream) error {
	fs.addTransmit(&TransmitChunk{
		ConsoleLogLines: []string{u.Record.Line},
	})
	return nil
}

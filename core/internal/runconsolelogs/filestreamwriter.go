package runconsolelogs

import (
	"encoding/json"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/sparselist"
)

// filestreamWriter sends modified console log lines to the filestream.
type filestreamWriter struct {
	FileStream filestream.FileStream

	// StructuredLogs indicates whether to send structured logs.
	Structured bool
}

func (w *filestreamWriter) SendChanged(
	changes sparselist.SparseList[*RunLogsLine],
) {
	lines := sparselist.Map(changes, func(line *RunLogsLine) string {
		if w.Structured {
			jsonLine, err := json.Marshal(line)
			if err != nil {
				return err.Error()
			}
			return string(jsonLine)
		}

		return line.LegacyFormat()
	})

	w.FileStream.StreamUpdate(&filestream.LogsUpdate{
		Lines: lines,
	})
}

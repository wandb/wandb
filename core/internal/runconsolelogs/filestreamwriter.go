package runconsolelogs

import (
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/sparselist"
)

// filestreamWriter sends modified console log lines to the filestream.
type filestreamWriter struct {
	FileStream filestream.FileStream

	// Structured controls the format of uploaded lines.
	//
	// If false, then the legacy plain text format is used:
	//
	// ERROR 2023-04-05T10:15:30.000000 [node-1-rank-0] Critical error occurred
	//
	// If true, then the JSON format is used:
	//
	//  {
	//    "level":"error",
	//    "ts":"2023-04-05T10:15:30.000000",
	//    "label":"node-1-rank-0",
	//    "content":"Division by zero",
	//  }
	Structured bool
}

func (w *filestreamWriter) SendChanged(
	changes sparselist.SparseList[*RunLogsLine],
) {
	lines := sparselist.Map(changes, func(line *RunLogsLine) string {
		if w.Structured {
			s, err := line.StructuredFormat()
			if err != nil {
				return line.LegacyFormat()
			}
			return s
		}

		return line.LegacyFormat()
	})

	w.FileStream.StreamUpdate(&filestream.LogsUpdate{
		Lines: lines,
	})
}

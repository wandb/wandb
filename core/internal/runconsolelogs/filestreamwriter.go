package runconsolelogs

import (
	"fmt"
	"strings"

	"github.com/wandb/wandb/core/internal/collections"
	"github.com/wandb/wandb/core/internal/filestream"
)

// filestreamWriter sends modified console log lines to the filestream.
type filestreamWriter struct {
	FileStream filestream.FileStream
}

func (w *filestreamWriter) SendChanged(
	changes collections.SparseList[*RunLogsLine],
) {
	// Generate timestamps in the Python ISO format (microseconds without Z)
	const rfc3339Micro = "2006-01-02T15:04:05.000000Z07:00"

	lines := collections.MapSparseList(
		changes,
		func(line *RunLogsLine) string {
			timestamp := strings.TrimSuffix(
				line.Timestamp.UTC().Format(rfc3339Micro), "Z")

			return fmt.Sprintf(
				"%s%s %s",
				line.StreamPrefix,
				timestamp,
				string(line.Content),
			)
		})

	w.FileStream.StreamUpdate(&filestream.LogsUpdate{
		Lines: lines,
	})
}

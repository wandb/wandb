package runconsolelogs

import (
	"fmt"
	"strings"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/sparselist"
)

// filestreamWriter sends modified console log lines to the filestream.
type filestreamWriter struct {
	FileStream filestream.FileStream
}

func (w *filestreamWriter) SendChanged(lineNum int, line RunLogsLine) {
	// Generate a timestamp in the Python ISO format (microseconds without Z)
	rfc3339Micro := "2006-01-02T15:04:05.000000Z07:00"
	timestamp := strings.TrimSuffix(line.Timestamp.UTC().Format(rfc3339Micro), "Z")

	list := sparselist.SparseList[string]{}
	list.Put(lineNum,
		fmt.Sprintf(
			"%s%s %s",
			line.StreamPrefix,
			timestamp,
			string(line.Content),
		))

	w.FileStream.StreamUpdate(&filestream.LogsUpdate{
		Lines: list,
	})
}

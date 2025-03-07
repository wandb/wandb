package runconsolelogs

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/sparselist"
)

// filestreamWriter sends modified console log lines to the filestream.
type filestreamWriter struct {
	FileStream filestream.FileStream

	// StructuredLogs indicates whether to send structured logs.
	Structured bool
}

type logLine struct {
	Level   string `json:"level,omitempty"`
	TS      string `json:"ts"`
	Label   string `json:"label,omitempty"`
	Content string `json:"content"`
}

// Timestamps are generated in the Python ISO format (microseconds without Z)
const rfc3339Micro = "2006-01-02T15:04:05.000000Z07:00"

// MarshalJSON implements the json.Marshaler interface.
func (r *RunLogsLine) MarshalJSON() ([]byte, error) {
	// Format timestamp and trim the Z suffix as specified
	timestamp := strings.TrimSuffix(r.Timestamp.UTC().Format(rfc3339Micro), "Z")

	// Convert rune slice to string for content
	content := string(r.Content)

	// We only indicate the log level if it is an error
	level := ""
	if r.StreamPrefix != "" {
		level = "error"
	}

	// Create the JSON structure with the required fields
	jsonLine := logLine{
		Level:   level,
		TS:      timestamp,
		Label:   r.StreamLabel,
		Content: content,
	}

	// Marshal the custom struct to JSON
	return json.Marshal(jsonLine)
}

func (line *RunLogsLine) legacyFormat() string {
	timestamp := strings.TrimSuffix(line.Timestamp.UTC().Format(rfc3339Micro), "Z")
	if line.StreamLabel != "" {
		return fmt.Sprintf(
			"%s%s [%s] %s",
			line.StreamPrefix,
			timestamp,
			line.StreamLabel,
			string(line.Content),
		)
	}
	return fmt.Sprintf(
		"%s%s %s",
		line.StreamPrefix,
		timestamp,
		string(line.Content),
	)
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

		return line.legacyFormat()
	})

	w.FileStream.StreamUpdate(&filestream.LogsUpdate{
		Lines: lines,
	})
}

package observabilitytest

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/observability"
)

// NewTestLogger returns a logger that's captured by the testing framework.
//
// Messages from this logger at or above INFO level are displayed in the test
// output on failure which can be helpful for debugging.
func NewTestLogger(t *testing.T) *observability.CoreLogger {
	t.Helper()
	return observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(t.Output(), &slog.HandlerOptions{})),
		analytics.NewTelemetryRecorder(nil, analytics.NewTelemetryContext()),
	)
}

// NewRecordingTestLogger is like NewTestLogger but also returns a buffer
// that captures log messages.
func NewRecordingTestLogger(t *testing.T) (
	*observability.CoreLogger,
	*bytes.Buffer,
) {
	t.Helper()
	return newRecordingTestLogger(t, slog.LevelInfo)
}

// NewDebugRecordingTestLogger is like NewRecordingTestLogger but also
// captures messages below the INFO level.
func NewDebugRecordingTestLogger(t *testing.T) (
	*observability.CoreLogger,
	*bytes.Buffer,
) {
	t.Helper()
	return newRecordingTestLogger(t, slog.LevelDebug)
}

// newRecordingTestLogger returns a logger that records messages at or
// above the given level into the returned buffer.
func newRecordingTestLogger(t *testing.T, level slog.Level) (
	*observability.CoreLogger,
	*bytes.Buffer,
) {
	t.Helper()

	recordedLogs := &bytes.Buffer{}
	writer := io.MultiWriter(t.Output(), recordedLogs)

	return observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(
			writer,
			&slog.HandlerOptions{Level: level},
		)),
		analytics.NewTelemetryRecorder(nil, analytics.NewTelemetryContext()),
	), recordedLogs
}

// ExtractLogs extracts structured logs from the [NewRecordingTestLogger]
// buffer, dropping keys not useful for testing.
//
// Specifically, the "time" key is dropped. Records will always contain
// the "level" and "msg" keys, plus custom slog attrs.
func ExtractLogs(t *testing.T, buf *bytes.Buffer) []map[string]string {
	records := make([]map[string]string, 0)

	// The JSONHandler encodes newlines as \n, so the only actual newlines
	// are used to separate records.
	for line := range bytes.Lines(buf.Bytes()) {
		var record map[string]string
		require.NoError(t, json.Unmarshal(line, &record))

		delete(record, "time")

		records = append(records, record)
	}

	return records
}

package observabilitytest

import (
	"bytes"
	"io"
	"log/slog"
	"testing"

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
		nil,
	)
}

// NewRecordingTestLogger is like NewTestLogger but also returns a buffer
// that captures log messages.
func NewRecordingTestLogger(t *testing.T) (
	*observability.CoreLogger,
	*bytes.Buffer,
) {
	t.Helper()

	recordedLogs := &bytes.Buffer{}
	writer := io.MultiWriter(t.Output(), recordedLogs)

	return observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(writer, &slog.HandlerOptions{})),
		nil,
	), recordedLogs
}

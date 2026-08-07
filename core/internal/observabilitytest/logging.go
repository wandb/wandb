package observabilitytest

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"testing"

	"github.com/getsentry/sentry-go"
	"github.com/stretchr/testify/require"

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

// NewSentryTestLogger is like NewRecordingTestLogger but also returns a
// mock Sentry transport for checking captured events.
func NewSentryTestLogger(t *testing.T) (
	*observability.CoreLogger,
	*bytes.Buffer,
	*sentry.MockTransport,
) {
	t.Helper()

	recordedLogs := &bytes.Buffer{}
	writer := io.MultiWriter(t.Output(), recordedLogs)

	transport := &sentry.MockTransport{}
	client, err := sentry.NewClient(sentry.ClientOptions{Transport: transport})
	require.NoError(t, err)
	hub := sentry.NewHub(client, sentry.NewScope())

	return observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(writer, &slog.HandlerOptions{})),
		observability.NewSentryContext(hub),
	), recordedLogs, transport
}

// ExtractLogs extracts structured logs from the [NewRecordingTestLogger]
// buffer, dropping keys not useful for testing.
//
// Specifically, the "time" key is dropped. Records will always contain
// the "level" and "msg" keys, plus custom slog attrs.
//
// Attr values keep their JSON types, so an int64 attr comes back as a float64
// and a bool attr as a bool.
func ExtractLogs(t *testing.T, buf *bytes.Buffer) []map[string]any {
	t.Helper()

	records := make([]map[string]any, 0)

	// The JSONHandler encodes newlines as \n, so the only actual newlines
	// are used to separate records.
	for line := range bytes.Lines(buf.Bytes()) {
		var record map[string]any
		require.NoError(t, json.Unmarshal(line, &record))

		delete(record, "time")

		records = append(records, record)
	}

	return records
}

// ExtractLogsAtOrAbove is like [ExtractLogs], but only returns the records
// logged at or above the given level.
func ExtractLogsAtOrAbove(
	t *testing.T,
	buf *bytes.Buffer,
	level slog.Level,
) []map[string]any {
	t.Helper()

	records := make([]map[string]any, 0)

	for _, record := range ExtractLogs(t, buf) {
		if recordLevel(t, record) >= level {
			records = append(records, record)
		}
	}

	return records
}

// AssertNoLogsAtOrAbove fails the test if anything was logged at or above the
// given level, reporting the offending records.
//
// Use this to assert that a code path is silent. For example, that reading a
// transaction log written by an older client emits no diagnostics that the
// older client would not have emitted for the same log.
func AssertNoLogsAtOrAbove(t *testing.T, buf *bytes.Buffer, level slog.Level) {
	t.Helper()

	records := ExtractLogsAtOrAbove(t, buf, level)
	if len(records) == 0 {
		return
	}

	// Only detail the first few records: a bug that logs once per history row
	// can produce thousands of them, which would bury the failure message.
	const maxDetailed = 5

	detail := &strings.Builder{}
	for _, record := range records[:min(len(records), maxDetailed)] {
		fmt.Fprintf(detail, "\n\t%v %v", record["level"], record["msg"])
	}
	if len(records) > maxDetailed {
		fmt.Fprintf(detail, "\n\t...and %d more", len(records)-maxDetailed)
	}

	t.Errorf("expected no logs at or above %v, but found %d:%s",
		level, len(records), detail)
}

// recordLevel returns the level of a record extracted by [ExtractLogs].
//
// A record whose level is missing or unparseable fails the test rather than
// being skipped, which would silently weaken the caller's assertion.
func recordLevel(t *testing.T, record map[string]any) slog.Level {
	t.Helper()

	text, ok := record["level"].(string)
	require.Truef(t, ok, `log record has no string "level" key: %v`, record)

	var level slog.Level
	require.NoErrorf(t, level.UnmarshalText([]byte(text)),
		"log record has an unparseable level %q", text)

	return level
}

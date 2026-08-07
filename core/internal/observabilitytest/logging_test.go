package observabilitytest_test

import (
	"log/slog"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
)

func TestExtractLogs_TolerantOfNonStringAttrs(t *testing.T) {
	logger, logs := observabilitytest.NewRecordingTestLogger(t)

	logger.Warn("renumbered",
		"provided_step", int64(3),
		"assigned_step", int64(10),
		"clamped", true)

	records := observabilitytest.ExtractLogs(t, logs)

	require.Len(t, records, 1)
	assert.Equal(t, map[string]any{
		"level": "WARN",
		"msg":   "renumbered",

		// JSON numbers decode as float64, since the record is a map[string]any.
		"provided_step": float64(3),
		"assigned_step": float64(10),

		"clamped": true,
	}, records[0])
}

func TestExtractLogs_EmptyBuffer(t *testing.T) {
	_, logs := observabilitytest.NewRecordingTestLogger(t)

	assert.Empty(t, observabilitytest.ExtractLogs(t, logs))
}

func TestExtractLogsAtOrAbove_FiltersByLevel(t *testing.T) {
	logger, logs := observabilitytest.NewRecordingTestLogger(t)

	// The test logger's handler drops records below INFO, so DEBUG never
	// reaches the buffer to be filtered.
	logger.Info("info message")
	logger.Warn("warn message")
	logger.Error("error message")

	records := observabilitytest.ExtractLogsAtOrAbove(t, logs, slog.LevelWarn)

	require.Len(t, records, 2)
	assert.Equal(t, "warn message", records[0]["msg"])
	assert.Equal(t, "error message", records[1]["msg"])
}

func TestAssertNoLogsAtOrAbove_PassesWhenNothingWasLogged(t *testing.T) {
	_, logs := observabilitytest.NewRecordingTestLogger(t)

	observabilitytest.AssertNoLogsAtOrAbove(t, logs, slog.LevelWarn)
}

func TestAssertNoLogsAtOrAbove_PassesWhenOnlyLowerLevelsWereLogged(t *testing.T) {
	logger, logs := observabilitytest.NewRecordingTestLogger(t)

	logger.Info("info message")

	observabilitytest.AssertNoLogsAtOrAbove(t, logs, slog.LevelWarn)
}

package runsync

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"time"

	"github.com/wandb/wandb/core/internal/fileutil"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
)

// DebugSyncLogFile is the log file for wandb sync.
type DebugSyncLogFile os.File

// Writer returns the io.Writer for writing to this file.
//
// If the file is nil, returns io.Discard.
func (f *DebugSyncLogFile) Writer() io.Writer {
	if f == nil {
		return io.Discard
	} else {
		return (*os.File)(f)
	}
}

// Close closes the file if it's not nil.
func (f *DebugSyncLogFile) Close() {
	if f == nil {
		return
	}

	err := (*os.File)(f).Close()
	if err != nil {
		slog.Error("runsync: error closing logger", "error", err)
	}
}

// OpenDebugSyncLogFile opens a file for writing wandb sync log messages.
func OpenDebugSyncLogFile(
	settings *settings.Settings,
) (*DebugSyncLogFile, error) {
	dir := filepath.Join(settings.GetWandbDir(), "logs")

	// 0o755: read-write-list for user; read-list for others.
	err := os.MkdirAll(dir, 0o755)
	if err != nil {
		return nil, err
	}

	now := time.Now()
	dateStr := now.Format("20060102")
	timeStr := now.Format("150405")

	file, err := fileutil.CreateUnique(
		filepath.Join(dir,
			fmt.Sprintf("debug-sync.%s.%s", dateStr, timeStr)),
		"log",
		0o644,
	)

	if err != nil {
		return nil, err
	}

	return (*DebugSyncLogFile)(file), err
}

// NewSyncLogger returns the logger to use for syncing.
func NewSyncLogger(
	logFile *DebugSyncLogFile,
	logLevel slog.Level,
) *observability.CoreLogger {
	return observability.NewCoreLogger(
		slog.New(
			slog.NewJSONHandler(
				logFile.Writer(),
				&slog.HandlerOptions{Level: logLevel},
			)),
		nil,
	)
}

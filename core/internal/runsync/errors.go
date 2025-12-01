package runsync

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/observability"
)

// SyncError is a failure that prevents syncing a run.
type SyncError struct {
	Err     error  // wrapped error
	Message string // Go-style error message (not including Err)

	// UserText is text to show to the user to explain the problem.
	//
	// It must be capitalized and punctuated. If empty, the user
	// should be shown text like "Internal error."
	UserText string
}

// Error implements error.Error.
func (e *SyncError) Error() string {
	return fmt.Sprintf("%s: %s", e.Message, e.Err.Error())
}

// LogOrCapture logs the error, capturing it if UserText is unset.
func (e *SyncError) LogOrCapture(logger *observability.CoreLogger) {
	if e.UserText == "" {
		logger.CaptureError(e)
	} else {
		logger.Error(e.Error())
	}
}

// logSyncFailure logs and possibly captures an error that prevents sync
// from succeeding.
func logSyncFailure(logger *observability.CoreLogger, err error) {
	if syncErr, ok := err.(*SyncError); ok && syncErr.UserText != "" {
		logger.Error(syncErr.Error())
	} else {
		// Any other errors are captured as they are unexpected
		// and don't have helpful user text.
		//
		// If you're here from Sentry, please figure out where
		// the error happens and wrap it in a SyncError with
		// proper UserText. Or fix it so it can't happen.
		logger.CaptureError(err)
	}
}

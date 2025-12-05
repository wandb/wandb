package runsync

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// SyncError is a failure that prevents syncing a run.
type SyncError struct {
	Err     error  // wrapped error, which may be nil
	Message string // Go-style error message (not including Err)

	// UserText is text to show to the user to explain the problem.
	//
	// It must be capitalized and punctuated. If empty, the user
	// should be shown text like "Internal error."
	UserText string
}

// Error implements error.Error.
func (e *SyncError) Error() string {
	if e.Err != nil {
		return fmt.Sprintf("%s: %s", e.Message, e.Err.Error())
	} else {
		return e.Message
	}
}

// LogSyncFailure logs and possibly captures an error that prevents sync
// from succeeding.
func LogSyncFailure(logger *observability.CoreLogger, err error) {
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

// ToUserText returns user-facing text for the error, which may be a SyncError.
func ToUserText(err error) string {
	syncErr, ok := err.(*SyncError)
	if !ok || syncErr.UserText == "" {
		return fmt.Sprintf("Internal error: %v", err)
	} else {
		return syncErr.UserText
	}
}

// ToSyncErrorMessage converts the error, which may be a SyncError,
// into a ServerSyncMessage to display to the user.
func ToSyncErrorMessage(err error) *spb.ServerSyncMessage {
	return &spb.ServerSyncMessage{
		Severity: spb.ServerSyncMessage_SEVERITY_ERROR,
		Content:  ToUserText(err),
	}
}

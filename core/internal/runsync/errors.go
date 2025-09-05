package runsync

import (
	"fmt"
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

package runmetadata

import (
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type runUpdateError struct {
	// UserMessage is error text to show to a user.
	//
	// It should start with a capital letter and end with punctuation
	// or additional information like a JSON value.
	UserMessage string

	// Cause is the source error, meant for logging.
	Cause error

	// Code indicates what generally went wrong.
	Code spb.ErrorInfo_ErrorCode
}

// AsResult returns the RunUdpateResult proto for the error.
func (e *runUpdateError) AsResult() *spb.RunUpdateResult {
	return &spb.RunUpdateResult{
		Error: &spb.ErrorInfo{
			Message: e.UserMessage,
			Code:    e.Code,
		},
	}
}

// Error returns the cause of a problem, for debugging.
func (e *runUpdateError) Error() string {
	return e.Cause.Error()
}

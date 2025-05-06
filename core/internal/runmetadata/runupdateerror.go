package runmetadata

import (
	"errors"

	"github.com/wandb/wandb/core/internal/runbranch"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// runUpdateErrorFromBranchError converts a resume, rewind or fork error
// to a runUpdateError.
//
// Other values including nil are returned unchanged.
func runUpdateErrorFromBranchError(err error) error {
	if err == nil {
		return nil
	}

	var runBranchError *runbranch.BranchError
	if errors.As(err, &runBranchError) {
		return &RunUpdateError{
			Cause:       runBranchError.Err,
			UserMessage: runBranchError.Response.GetMessage(),
			Code:        runBranchError.Response.GetCode(),
		}
	}

	return err
}

type RunUpdateError struct {
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
func (e *RunUpdateError) AsResult() *spb.RunUpdateResult {
	return &spb.RunUpdateResult{
		Error: &spb.ErrorInfo{
			Message: e.UserMessage,
			Code:    e.Code,
		},
	}
}

// Error returns the cause of a problem, for debugging.
func (e *RunUpdateError) Error() string {
	return e.Cause.Error()
}

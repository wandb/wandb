package runupserter

import (
	"context"
	"errors"
	"fmt"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/runbranch"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ToRunUpdateError converts error types seen by the runupserter
// into RunUpdateError.
//
// Generic errors including nil are returned unchanged.
func ToRunUpdateError(err error) error {
	if err == nil {
		return nil
	}

	if runBranchError, ok := errors.AsType[*runbranch.BranchError](err); ok {
		return fromRunBranchError(runBranchError)
	}

	if gqlError, ok := errors.AsType[*graphql.HTTPError](err); ok {
		return fromGQLError(gqlError)
	}

	if errors.Is(err, context.DeadlineExceeded) {
		return fromTimeout(err)
	}

	return err
}

func fromRunBranchError(runBranchError *runbranch.BranchError) *RunUpdateError {
	return &RunUpdateError{
		Cause:       runBranchError.Err,
		UserMessage: runBranchError.Response.GetMessage(),
		Code:        runBranchError.Response.GetCode(),
	}
}

func fromGQLError(gqlError *graphql.HTTPError) *RunUpdateError {
	userMessage := api.FormatGQLErrors(gqlError.Response)

	if userMessage == "" {
		// An empty UserMessage is treated like "no error" by the client.
		//
		// This can happen if the backend returns an empty response and
		// an error status.
		userMessage = "<no message>"
	}

	return &RunUpdateError{
		Cause:       gqlError,
		UserMessage: userMessage,
		Code:        spb.ErrorInfo_COMMUNICATION,
	}
}

func fromTimeout(err error) *RunUpdateError {
	const timeoutSettingHint = "" +
		"Consider increasing the init_timeout setting:" +
		"\n  wandb.init(settings=wandb.Settings(init_timeout=...))"

	var userMessage string
	if retryErr, ok := errors.AsType[*api.RetryError](err); ok {
		userMessage = fmt.Sprintf("Timed out while retrying: %s", retryErr.LastStatus)
	} else {
		userMessage = fmt.Sprintf("Timed out initializing run: %s", err.Error())
	}

	return &RunUpdateError{
		Cause:       err,
		UserMessage: fmt.Sprintf("%s\n%s", userMessage, timeoutSettingHint),
		Code:        spb.ErrorInfo_COMMUNICATION,
	}
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

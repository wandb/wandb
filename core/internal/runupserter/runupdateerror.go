package runupserter

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/runbranch"
	"github.com/wandb/wandb/core/internal/wboperation"
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

	var runBranchError *runbranch.BranchError
	if errors.As(err, &runBranchError) {
		return fromRunBranchError(runBranchError)
	}

	var gqlError *graphql.HTTPError
	if errors.As(err, &gqlError) {
		return fromGQLError(gqlError)
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
	var userMessage string

	switch {
	case len(gqlError.Response.Errors) == 0:
		userMessage = gqlError.Error()
	case len(gqlError.Response.Errors) == 1:
		userMessage = gqlError.Response.Errors[0].Message
	default:
		var messages []string
		for _, err := range gqlError.Response.Errors {
			messages = append(messages, err.Message)
		}
		joinedMessages := strings.Join(messages, "; ")
		userMessage = fmt.Sprintf("[%s]", joinedMessages)
	}

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

// explainInitTimeout enhances errors caused by reaching the client's init
// timeout during run initialization.
//
// If the error is the operation's context reaching its deadline, it is
// converted to a RunUpdateError whose message includes the operation's
// error status—usually the error that was being retried. Other errors,
// including nil, are returned unchanged.
func explainInitTimeout(
	err error,
	operation *wboperation.WandbOperation,
) error {
	if !errors.Is(err, context.DeadlineExceeded) {
		return err
	}

	userMessage := "Timed out while creating the run."
	if status := operation.ErrorStatus(); status != "" {
		userMessage = fmt.Sprintf("%s Last status: %s.", userMessage, status)
	}

	return &RunUpdateError{
		Cause:       err,
		UserMessage: userMessage,
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

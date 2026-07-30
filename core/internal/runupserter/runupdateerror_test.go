package runupserter_test

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/vektah/gqlparser/v2/gqlerror"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/runbranch"
	"github.com/wandb/wandb/core/internal/runupserter"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func Test_ToRunUpdateError_BranchError(t *testing.T) {
	err := &runbranch.BranchError{
		Err: errors.New("test err"),
		Response: &spb.ErrorInfo{
			Message: "test error message",
			Code:    spb.ErrorInfo_UNSUPPORTED,
		},
	}

	result := runupserter.ToRunUpdateError(err)

	runUpdateError := result.(*runupserter.RunUpdateError)
	assert.ErrorContains(t, runUpdateError, "test err")
	assert.Equal(t, "test error message", runUpdateError.UserMessage)
	assert.Equal(t, spb.ErrorInfo_UNSUPPORTED, runUpdateError.Code)
}

func Test_ToRunUpdateError_GQLError(t *testing.T) {
	err := &graphql.HTTPError{
		StatusCode: 400,
		Response: graphql.Response{
			Errors: gqlerror.List{
				{Message: "gql error message"},
			},
		},
	}

	result := runupserter.ToRunUpdateError(err)

	runUpdateError := result.(*runupserter.RunUpdateError)
	assert.ErrorContains(t, runUpdateError, "400") // from HTTPError.Error()
	assert.Equal(t, "gql error message", runUpdateError.UserMessage)
	assert.Equal(t, spb.ErrorInfo_COMMUNICATION, runUpdateError.Code)
}

func Test_ToRunUpdateError_GQLError_Empty(t *testing.T) {
	err := &graphql.HTTPError{
		StatusCode: 400,
		Response: graphql.Response{
			Errors: gqlerror.List{{Message: ""}}, // no error body (unusual)
		},
	}

	result := runupserter.ToRunUpdateError(err)

	runUpdateError := result.(*runupserter.RunUpdateError)
	assert.ErrorContains(t, runUpdateError, "400") // from HTTPError.Error()
	assert.Contains(t, runUpdateError.UserMessage, "<no message>")
}

func Test_ToRunUpdateError_RawTimeout(t *testing.T) {
	err := fmt.Errorf("some extra info: %w", context.DeadlineExceeded)

	result := runupserter.ToRunUpdateError(err)

	runUpdateError := result.(*runupserter.RunUpdateError)
	assert.Equal(t, spb.ErrorInfo_COMMUNICATION, runUpdateError.Code)
	assert.Equal(t,
		"Timed out initializing run: some extra info: context deadline exceeded"+
			"\nConsider increasing the init_timeout setting:"+
			"\n  wandb.init(settings=wandb.Settings(init_timeout=...))",
		runUpdateError.UserMessage)
	assert.Equal(t,
		"some extra info: context deadline exceeded",
		runUpdateError.Error())
}

func Test_ToRunUpdateError_EnhancedTimeout(t *testing.T) {
	err := &api.RetryError{
		Inner:      context.DeadlineExceeded,
		LastStatus: "HTTP 500: oops",
	}

	result := runupserter.ToRunUpdateError(err)

	runUpdateError := result.(*runupserter.RunUpdateError)
	assert.Equal(t, spb.ErrorInfo_COMMUNICATION, runUpdateError.Code)
	assert.Equal(t,
		"Timed out while retrying: HTTP 500: oops"+
			"\nConsider increasing the init_timeout setting:"+
			"\n  wandb.init(settings=wandb.Settings(init_timeout=...))",
		runUpdateError.UserMessage)
	assert.Equal(t,
		"context deadline exceeded\nwhile retrying: HTTP 500: oops",
		runUpdateError.Error())
}

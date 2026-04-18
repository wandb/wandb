package runupserter_test

import (
	"errors"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/vektah/gqlparser/v2/gqlerror"

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

func Test_ToRunUpdateError_GQLError_One(t *testing.T) {
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

func Test_ToRunUpdateError_GQLError_Many(t *testing.T) {
	err := &graphql.HTTPError{
		StatusCode: 400,
		Response: graphql.Response{
			Errors: gqlerror.List{
				{Message: "gql 1"},
				{Message: "gql 2"},
			},
		},
	}

	result := runupserter.ToRunUpdateError(err)

	runUpdateError := result.(*runupserter.RunUpdateError)
	assert.ErrorContains(t, runUpdateError, "400") // from HTTPError.Error()
	assert.Equal(t, "[gql 1; gql 2]", runUpdateError.UserMessage)
	assert.Equal(t, spb.ErrorInfo_COMMUNICATION, runUpdateError.Code)
}

func Test_ToRunUpdateError_GQLError_None(t *testing.T) {
	err := &graphql.HTTPError{
		StatusCode: 400,
		Response:   graphql.Response{}, // no GQL errors (unusual)
	}

	result := runupserter.ToRunUpdateError(err)

	runUpdateError := result.(*runupserter.RunUpdateError)
	assert.ErrorContains(t, runUpdateError, "400") // from HTTPError.Error()
	assert.Contains(t, runUpdateError.UserMessage, "400")
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

package api_test

import (
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/vektah/gqlparser/v2/gqlerror"

	"github.com/wandb/wandb/core/internal/api"
)

func Test_FormatGQLErrors_GQLError_One(t *testing.T) {
	response := graphql.Response{
		Errors: gqlerror.List{
			{Message: "gql error message"},
		},
	}

	result := api.FormatGQLErrors(response)

	assert.Equal(t, "gql error message", result)
}

func Test_FormatGQLErrors_GQLError_Many(t *testing.T) {
	response := graphql.Response{
		Errors: gqlerror.List{
			{Message: "gql 1"},
			{Message: "gql 2"},
		},
	}

	result := api.FormatGQLErrors(response)

	assert.Equal(t, "[gql 1; gql 2]", result)
}

func Test_FormatGQLErrors_GQLError_None(t *testing.T) {
	response := graphql.Response{}

	result := api.FormatGQLErrors(response)

	assert.Empty(t, result)
}

func Test_MaybeGQLErrorResponse(t *testing.T) {
	result := api.MaybeGQLErrorResponse([]byte(`
		{"errors": [
			{"message": "err 1"},
			{"message": "err 2"}
		]}`))

	assert.Equal(t, "[err 1; err 2]", result)
}

func Test_MaybeGQLErrorResponse_Incomplete(t *testing.T) {
	result := api.MaybeGQLErrorResponse([]byte(`{"errors": [`))

	assert.Empty(t, result)
}

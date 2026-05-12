package wbapi_test

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/vektah/gqlparser/v2/gqlerror"

	"github.com/wandb/wandb/core/internal/wbapi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type recordingGraphQLClient struct {
	request *graphql.Request
	data    string
	err     error
}

func (c *recordingGraphQLClient) MakeRequest(
	ctx context.Context,
	request *graphql.Request,
	response *graphql.Response,
) error {
	c.request = request
	if c.err != nil {
		return c.err
	}
	return json.Unmarshal([]byte(c.data), response.Data)
}

func TestGraphQLHandlerExecutesRequest(t *testing.T) {
	client := &recordingGraphQLClient{
		data: `{"viewer":{"id":"user-id"}}`,
	}
	handler := wbapi.NewGraphQLHandler(client)

	response := handler.HandleRequest(context.Background(), &spb.GraphQLRequest{
		Query:         "query Viewer($step: Int64!) { viewer { id } }",
		VariablesJson: `{"step":9007199254740993}`,
	})

	require.NotNil(t, response.GetGraphqlResponse())
	assert.JSONEq(t,
		`{"viewer":{"id":"user-id"}}`,
		response.GetGraphqlResponse().GetDataJson(),
	)
	require.NotNil(t, client.request)
	assert.Equal(t, "query Viewer($step: Int64!) { viewer { id } }", client.request.Query)

	variables, ok := client.request.Variables.(map[string]any)
	require.True(t, ok)
	step, ok := variables["step"].(json.Number)
	require.True(t, ok)
	assert.Equal(t, "9007199254740993", step.String())
}

func TestGraphQLHandlerRejectsInvalidVariables(t *testing.T) {
	handler := wbapi.NewGraphQLHandler(&recordingGraphQLClient{})

	response := handler.HandleRequest(context.Background(), &spb.GraphQLRequest{
		Query:         "query Viewer { viewer { id } }",
		VariablesJson: "{",
	})

	require.NotNil(t, response.GetApiErrorResponse())
	assert.Contains(t, response.GetApiErrorResponse().GetMessage(), "decode GraphQL variables")
}

func TestGraphQLHandlerReturnsGraphQLError(t *testing.T) {
	handler := wbapi.NewGraphQLHandler(&recordingGraphQLClient{
		err: errors.New("server unavailable"),
	})

	response := handler.HandleRequest(context.Background(), &spb.GraphQLRequest{
		Query: "query Viewer { viewer { id } }",
	})

	require.NotNil(t, response.GetApiErrorResponse())
	assert.Equal(t, "server unavailable", response.GetApiErrorResponse().GetMessage())
}

func TestGraphQLHandlerReturnsHTTPGraphQLErrorMessage(t *testing.T) {
	handler := wbapi.NewGraphQLHandler(&recordingGraphQLClient{
		err: &graphql.HTTPError{
			StatusCode: 400,
			Response: graphql.Response{
				Errors: gqlerror.List{
					{Message: "first GraphQL error"},
					{Message: "second GraphQL error"},
				},
			},
		},
	})

	response := handler.HandleRequest(context.Background(), &spb.GraphQLRequest{
		Query: "query Viewer { viewer { id } }",
	})

	require.NotNil(t, response.GetApiErrorResponse())
	assert.Equal(t,
		"[first GraphQL error; second GraphQL error]",
		response.GetApiErrorResponse().GetMessage(),
	)
}

func TestGraphQLHandlerFallsBackForHTTPErrorWithoutGraphQLErrors(t *testing.T) {
	handler := wbapi.NewGraphQLHandler(&recordingGraphQLClient{
		err: &graphql.HTTPError{StatusCode: 500},
	})

	response := handler.HandleRequest(context.Background(), &spb.GraphQLRequest{
		Query: "query Viewer { viewer { id } }",
	})

	require.NotNil(t, response.GetApiErrorResponse())
	assert.Contains(t, response.GetApiErrorResponse().GetMessage(), "returned error 500")
}

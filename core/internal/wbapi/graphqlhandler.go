package wbapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/Khan/genqlient/graphql"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// GraphQLHandler handles raw GraphQL requests for the public API.
type GraphQLHandler struct {
	graphqlClient graphql.Client
}

func NewGraphQLHandler(graphqlClient graphql.Client) *GraphQLHandler {
	return &GraphQLHandler{graphqlClient: graphqlClient}
}

// HandleRequest handles raw GraphQL requests from the public API.
//
// This is transitional code for moving public API requests off the old
// vendored Python GraphQL library and onto wandb-core.
// Once that transition is complete and the vendored code is removed, each
// individual query should move from a Python function to generated Go code.
// Python will still own the public API object model, but it should send
// operation-specific proto requests instead of raw GraphQL documents.
func (h *GraphQLHandler) HandleRequest(
	ctx context.Context,
	request *spb.GraphQLRequest,
) *spb.ApiResponse {
	var variables map[string]any
	if request.GetVariablesJson() != "" {
		decoder := json.NewDecoder(strings.NewReader(request.GetVariablesJson()))
		// Preserve integer precision when genqlient re-encodes variables.
		decoder.UseNumber()
		if err := decoder.Decode(&variables); err != nil {
			return apiErrorResponse(fmt.Sprintf("decode GraphQL variables: %v", err))
		}
	}

	var data json.RawMessage
	response := &graphql.Response{Data: &data}
	err := h.graphqlClient.MakeRequest(ctx, &graphql.Request{
		Query:     request.GetQuery(),
		Variables: variables,
	}, response)
	if err != nil {
		return apiErrorResponse(graphqlErrorMessage(err))
	}

	dataJSON := "null"
	if len(data) > 0 {
		dataJSON = string(data)
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_GraphqlResponse{
			GraphqlResponse: &spb.GraphQLResponse{
				DataJson: dataJSON,
			},
		},
	}
}

func apiErrorResponse(message string) *spb.ApiResponse {
	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ApiErrorResponse{
			ApiErrorResponse: &spb.ApiErrorResponse{
				Message: message,
			},
		},
	}
}

// graphqlErrorMessage returns a user-facing error message for a request
// failure from the GraphQL client.
//
// genqlient's *graphql.HTTPError stringifies as the JSON-encoded response
// body, which leaks `data` and unstructured fields into the message a user
// would see. When the body carries GraphQL `errors`, prefer their messages;
// otherwise fall back to the HTTPError's default rendering.
func graphqlErrorMessage(err error) string {
	var httpError *graphql.HTTPError
	if !errors.As(err, &httpError) {
		return err.Error()
	}

	message := httpGraphQLErrorMessage(httpError)
	if message == "" {
		return "<no message>"
	}
	return message
}

func httpGraphQLErrorMessage(httpError *graphql.HTTPError) string {
	switch {
	case len(httpError.Response.Errors) == 0:
		return httpError.Error()
	case len(httpError.Response.Errors) == 1:
		return httpError.Response.Errors[0].Message
	default:
		messages := make([]string, 0, len(httpError.Response.Errors))
		for _, err := range httpError.Response.Errors {
			messages = append(messages, err.Message)
		}
		return fmt.Sprintf("[%s]", strings.Join(messages, "; "))
	}
}

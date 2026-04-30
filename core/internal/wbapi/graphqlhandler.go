package wbapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/Khan/genqlient/graphql"
	"github.com/vektah/gqlparser/v2/gqlerror"

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

func graphqlErrorMessage(err error) string {
	var httpError *graphql.HTTPError
	if !errors.As(err, &httpError) {
		return err.Error()
	}

	message := graphqlErrorsMessage(httpError.Response.Errors)
	if message == "" {
		message = httpError.Error()
	}
	return message
}

func graphqlErrorsMessage(gqlErrors gqlerror.List) string {
	switch len(gqlErrors) {
	case 0:
		return ""
	case 1:
		if gqlErrors[0] == nil || gqlErrors[0].Message == "" {
			return "<no message>"
		}
		return gqlErrors[0].Message
	default:
		messages := make([]string, 0, len(gqlErrors))
		for _, gqlError := range gqlErrors {
			if gqlError == nil || gqlError.Message == "" {
				messages = append(messages, "<no message>")
				continue
			}
			messages = append(messages, gqlError.Message)
		}
		return fmt.Sprintf("[%s]", strings.Join(messages, "; "))
	}
}

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
			return apiErrorResponse(fmt.Sprintf("decode GraphQL variables: %v", err), 0)
		}
	}

	query, err := GQLCompatOptionsFromRequest(
		request.GetOmitVariables(),
		request.GetOmitFragments(),
		request.GetOmitFields(),
		request.GetRenameFields(),
	).RewriteQuery(request.GetQuery())
	if err != nil {
		return apiErrorResponse(err.Error(), 0)
	}

	var data json.RawMessage
	response := &graphql.Response{Data: &data}
	err = h.graphqlClient.MakeRequest(ctx, &graphql.Request{
		Query:     query,
		Variables: variables,
	}, response)
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
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

func apiErrorResponse(message string, httpStatus int32) *spb.ApiResponse {
	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ApiErrorResponse{
			ApiErrorResponse: &spb.ApiErrorResponse{
				Message:    message,
				HttpStatus: httpStatus,
			},
		},
	}
}

// graphqlErrorInfo returns a user-facing error message and the upstream HTTP
// status (0 if there was none) for a failed GraphQL request.
//
// genqlient's *graphql.HTTPError stringifies as the JSON-encoded response
// body, which leaks `data` and unstructured fields into the message a user
// would see. When the body carries GraphQL `errors`, prefer their messages;
// otherwise fall back to the HTTPError's default rendering.
func graphqlErrorInfo(err error) (string, int32) {
	var httpError *graphql.HTTPError
	if !errors.As(err, &httpError) {
		return err.Error(), 0
	}

	message := httpGraphQLErrorMessage(httpError)
	if message == "" {
		message = "<no message>"
	}
	return message, int32(httpError.StatusCode)
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

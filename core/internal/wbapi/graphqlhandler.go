package wbapi

import (
	"context"
	"encoding/json"
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
// Python should then drive those generated queries and mutations through a
// modified proto message that identifies the specific operation to invoke.
func (h *GraphQLHandler) HandleRequest(
	ctx context.Context,
	request *spb.GraphQLRequest,
) *spb.ApiResponse {
	var variables map[string]any
	if request.GetVariablesJson() != "" {
		decoder := json.NewDecoder(strings.NewReader(request.GetVariablesJson()))
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
		return apiErrorResponse(err.Error())
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

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

package wbapi

import (
	"context"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// CustomChartHandler handles custom-chart API requests through typed GraphQL
// operations executed by wandb-core.
type CustomChartHandler struct {
	graphqlClient graphql.Client
}

func NewCustomChartHandler(graphqlClient graphql.Client) *CustomChartHandler {
	return &CustomChartHandler{graphqlClient: graphqlClient}
}

// HandleCreateCustomChart creates a custom chart preset on the W&B backend.
//
// The response contains the chart ID if the chart was created successfully.
func (h *CustomChartHandler) HandleCreateCustomChart(
	ctx context.Context,
	request *spb.CreateCustomChartRequest,
) *spb.ApiResponse {
	result, err := gql.CreateCustomChart(
		ctx,
		h.graphqlClient,
		request.GetEntity(),
		request.GetName(),
		request.GetDisplayName(),
		request.GetSpecType(),
		request.GetAccess(),
		request.GetSpec(),
	)
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
	}

	if result.GetCreateCustomChart() == nil {
		return apiErrorResponse("failed to create custom chart", 0)
	}
	chart := result.GetCreateCustomChart().GetChart()
	chartID := chart.GetId()

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_CreateCustomChartResponse{
			CreateCustomChartResponse: &spb.CreateCustomChartResponse{
				ChartId: chartID,
			},
		},
	}
}

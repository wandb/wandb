package wbapi

import (
	"context"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunHandler handles run-level API requests that resolve to typed GraphQL
// operations executed by wandb-core.
type RunHandler struct {
	graphqlClient graphql.Client
}

func NewRunHandler(graphqlClient graphql.Client) *RunHandler {
	return &RunHandler{graphqlClient: graphqlClient}
}

// HandleStopRun flags a run to stop on the W&B backend.
//
// This is the same signal sent by the "Stop run" button in the W&B UI: the
// backend sets the run's stopped flag, which the process running the run
// polls during its heartbeat to shut the run down gracefully.
func (h *RunHandler) HandleStopRun(
	ctx context.Context,
	request *spb.StopRunRequest,
) *spb.ApiResponse {
	_, err := gql.StopRun(ctx, h.graphqlClient, request.GetStorageId())
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_StopRunResponse{
			StopRunResponse: &spb.StopRunResponse{},
		},
	}
}

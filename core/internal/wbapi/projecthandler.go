package wbapi

import (
	"context"
	"fmt"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ProjectHandler handles project-level API requests through typed GraphQL
// operations executed by wandb-core.
type ProjectHandler struct {
	graphqlClient graphql.Client
}

func NewProjectHandler(graphqlClient graphql.Client) *ProjectHandler {
	return &ProjectHandler{graphqlClient: graphqlClient}
}

// HandleGetProjectInternalID resolves a project's opaque internal ID.
func (h *ProjectHandler) HandleGetProjectInternalID(
	ctx context.Context,
	request *spb.GetProjectInternalIdRequest,
) *spb.ApiResponse {
	data, err := gql.ProjectInternalID(
		ctx,
		h.graphqlClient,
		request.GetEntity(),
		request.GetProject(),
	)
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
	}

	project := data.GetProject()
	if project == nil {
		return apiErrorResponse(
			fmt.Sprintf(
				"Unable to resolve W&B project %s/%s.",
				request.GetEntity(),
				request.GetProject(),
			),
			0,
		)
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_GetProjectInternalIdResponse{
			GetProjectInternalIdResponse: &spb.GetProjectInternalIdResponse{
				ProjectInternalId: project.GetInternalId(),
			},
		},
	}
}

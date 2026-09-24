package wbapi

import (
	"context"

	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/proto"

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

	response := &spb.GetProjectInternalIdResponse{}
	// The project is null when it does not exist or the credentials cannot
	// read it. Leave the optional ID unset so the caller can distinguish this
	// expected lookup result from a request failure.
	if project := data.GetProject(); project != nil {
		response.ProjectInternalId = proto.String(project.GetInternalId())
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_GetProjectInternalIdResponse{
			GetProjectInternalIdResponse: response,
		},
	}
}

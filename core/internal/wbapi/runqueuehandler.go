package wbapi

import (
	"context"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunQueueHandler handles run-queue API requests through typed GraphQL
// operations executed by wandb-core.
type RunQueueHandler struct {
	graphqlClient graphql.Client
}

func NewRunQueueHandler(graphqlClient graphql.Client) *RunQueueHandler {
	return &RunQueueHandler{graphqlClient: graphqlClient}
}

// HandleRequest dispatches the requested run-queue operation.
func (h *RunQueueHandler) HandleRequest(
	ctx context.Context,
	request *spb.RunQueueOperationRequest,
) *spb.ApiResponse {
	switch operation := request.Operation.(type) {
	case *spb.RunQueueOperationRequest_CreateDefaultResourceConfigRequest:
		return h.HandleCreateDefaultResourceConfig(
			ctx,
			operation.CreateDefaultResourceConfigRequest,
		)
	case *spb.RunQueueOperationRequest_CreateRunQueueRequest:
		return h.HandleCreateRunQueue(ctx, operation.CreateRunQueueRequest)
	case *spb.RunQueueOperationRequest_UpsertRunQueueRequest:
		return h.HandleUpsertRunQueue(ctx, operation.UpsertRunQueueRequest)
	default:
		return apiErrorResponse("unsupported operation", 0)
	}
}

func (h *RunQueueHandler) HandleCreateDefaultResourceConfig(
	ctx context.Context,
	request *spb.CreateDefaultResourceConfigRequest,
) *spb.ApiResponse {
	result, err := gql.CreateDefaultResourceConfig(
		ctx,
		h.graphqlClient,
		request.GetEntityName(),
		request.GetResource(),
		request.GetConfig(),
		request.TemplateVariables,
	)
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
	}

	payload := result.GetCreateDefaultResourceConfig()
	if payload == nil {
		return apiErrorResponse("failed to create default resource config", 0)
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_RunQueueOperationResponse{
			RunQueueOperationResponse: &spb.RunQueueOperationResponse{
				Operation: &spb.RunQueueOperationResponse_CreateDefaultResourceConfigResponse{
					CreateDefaultResourceConfigResponse: &spb.CreateDefaultResourceConfigResponse{
						Success:                 payload.GetSuccess(),
						DefaultResourceConfigId: payload.GetDefaultResourceConfigID(),
					},
				},
			},
		},
	}
}

func (h *RunQueueHandler) HandleCreateRunQueue(
	ctx context.Context,
	request *spb.CreateRunQueueRequest,
) *spb.ApiResponse {
	var prioritizationMode *gql.RunQueuePrioritizationMode
	if request.PrioritizationMode != nil {
		mode := gql.RunQueuePrioritizationMode(request.GetPrioritizationMode())
		prioritizationMode = &mode
	}

	result, err := gql.CreateRunQueue(
		ctx,
		h.graphqlClient,
		request.GetEntity(),
		request.GetProject(),
		request.GetQueueName(),
		gql.RunQueueAccessType(request.GetAccess()),
		prioritizationMode,
		request.DefaultResourceConfigId,
	)
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
	}

	payload := result.GetCreateRunQueue()
	if payload == nil {
		return apiErrorResponse("failed to create run queue", 0)
	}

	success := false
	if payload.GetSuccess() != nil {
		success = *payload.GetSuccess()
	}
	queueID := ""
	if payload.GetQueueID() != nil {
		queueID = *payload.GetQueueID()
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_RunQueueOperationResponse{
			RunQueueOperationResponse: &spb.RunQueueOperationResponse{
				Operation: &spb.RunQueueOperationResponse_CreateRunQueueResponse{
					CreateRunQueueResponse: &spb.CreateRunQueueResponse{
						Success: success,
						QueueId: queueID,
					},
				},
			},
		},
	}
}

func (h *RunQueueHandler) HandleUpsertRunQueue(
	ctx context.Context,
	request *spb.UpsertRunQueueRequest,
) *spb.ApiResponse {
	var prioritizationMode *gql.RunQueuePrioritizationMode
	if request.PrioritizationMode != nil {
		mode := gql.RunQueuePrioritizationMode(request.GetPrioritizationMode())
		prioritizationMode = &mode
	}

	result, err := gql.UpsertRunQueue(
		ctx,
		h.graphqlClient,
		request.GetEntityName(),
		request.GetProjectName(),
		request.GetQueueName(),
		request.GetResourceType(),
		request.GetResourceConfig(),
		request.TemplateVariables,
		prioritizationMode,
		request.ExternalLinks,
		request.ClientMutationId,
	)
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
	}

	payload := result.GetUpsertRunQueue()
	if payload == nil {
		return apiErrorResponse("failed to upsert run queue", 0)
	}

	success := false
	if payload.GetSuccess() != nil {
		success = *payload.GetSuccess()
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_RunQueueOperationResponse{
			RunQueueOperationResponse: &spb.RunQueueOperationResponse{
				Operation: &spb.RunQueueOperationResponse_UpsertRunQueueResponse{
					UpsertRunQueueResponse: &spb.UpsertRunQueueResponse{
						Success:                      success,
						ConfigSchemaValidationErrors: payload.GetConfigSchemaValidationErrors(),
					},
				},
			},
		},
	}
}

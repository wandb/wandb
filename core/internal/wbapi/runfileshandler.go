package wbapi

import (
	"context"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunFilesHandler handles run-file API requests that resolve to typed GraphQL
// operations executed by wandb-core.
type RunFilesHandler struct {
	graphqlClient graphql.Client
}

func NewRunFilesHandler(graphqlClient graphql.Client) *RunFilesHandler {
	return &RunFilesHandler{graphqlClient: graphqlClient}
}

// HandleMarkRunFilesUploaded tells the backend that run files uploaded directly
// to their (presigned) destination URLs have completed, so it finalizes them on
// the run (DB row, derivative generation, etc.).
//
// During a live run this is driven by the filestream "uploaded" field, but that
// path also advances the run's liveness and would resurrect a finished run. The
// markRunFilesUploaded mutation performs only the file-uploaded publish with no
// run-state side effects, so it is safe for files uploaded outside a run (e.g.
// the public API's Run.upload_file).
func (h *RunFilesHandler) HandleMarkRunFilesUploaded(
	ctx context.Context,
	request *spb.MarkRunFilesUploadedRequest,
) *spb.ApiResponse {
	if len(request.GetFiles()) == 0 {
		return markRunFilesUploadedResponse()
	}

	_, err := gql.MarkRunFilesUploaded(
		ctx,
		h.graphqlClient,
		request.GetEntity(),
		request.GetProject(),
		request.GetRunId(),
		request.GetFiles(),
	)
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
	}

	return markRunFilesUploadedResponse()
}

func markRunFilesUploadedResponse() *spb.ApiResponse {
	return &spb.ApiResponse{
		Response: &spb.ApiResponse_MarkRunFilesUploadedResponse{
			MarkRunFilesUploadedResponse: &spb.MarkRunFilesUploadedResponse{},
		},
	}
}

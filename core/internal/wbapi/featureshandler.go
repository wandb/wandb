package wbapi

import (
	"context"

	"github.com/wandb/wandb/core/internal/featurechecker"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// FeaturesHandler responds to feature requests.
type FeaturesHandler struct {
	featureProvider *featurechecker.FeatureProvider
}

func NewFeaturesHandler(
	featureProvider *featurechecker.FeatureProvider,
) *FeaturesHandler {
	return &FeaturesHandler{featureProvider: featureProvider}
}

// HandleRequest produces the response for a FeaturesRequest.
//
// Server-feature errors are logged and return default values.
func (h *FeaturesHandler) HandleRequest(
	ctx context.Context,
	request *spb.FeaturesRequest,
) *spb.ApiResponse {
	switch request := request.GetRequest().(type) {
	case *spb.FeaturesRequest_Server:
		return h.handleServerRequest(ctx, request.Server)
	case *spb.FeaturesRequest_Org:
		return h.handleOrgRequest(ctx, request.Org)
	default:
		return apiErrorResponse("unsupported features request", 0)
	}
}

// handleServerRequest returns the requested enabled server features.
func (h *FeaturesHandler) handleServerRequest(
	ctx context.Context,
	request *spb.ServerFeaturesRequest,
) *spb.ApiResponse {
	response := &spb.ServerFeaturesResponse{}

	for _, feature := range request.Features {
		if h.featureProvider.Enabled(ctx, feature) {
			response.Enabled = append(response.Enabled, feature)
		}
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_FeaturesResponse{
			FeaturesResponse: &spb.FeaturesResponse{
				Response: &spb.FeaturesResponse_Server{Server: response},
			},
		},
	}
}

// handleOrgRequest returns requested organization feature flags that exist.
func (h *FeaturesHandler) handleOrgRequest(
	ctx context.Context,
	request *spb.OrgFeaturesRequest,
) *spb.ApiResponse {
	requested := request.GetFeatures()
	if len(requested) > 0 && request.GetOrg() == "" {
		return apiErrorResponse(
			"org is required to check organization feature flags",
			0,
		)
	}

	features, err := h.featureProvider.OrgFeatures(
		ctx,
		request.GetOrg(),
		requested,
	)
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_FeaturesResponse{
			FeaturesResponse: &spb.FeaturesResponse{
				Response: &spb.FeaturesResponse_Org{
					Org: &spb.OrgFeaturesResponse{Features: features},
				},
			},
		},
	}
}

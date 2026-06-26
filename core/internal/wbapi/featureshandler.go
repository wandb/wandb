package wbapi

import (
	"context"

	"github.com/wandb/wandb/core/internal/featurechecker"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// FeaturesHandler responds to FeaturesRequests.
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
// It cannot error out: errors are logged and default values are returned.
func (h *FeaturesHandler) HandleRequest(
	ctx context.Context,
	request *spb.FeaturesRequest,
) *spb.ApiResponse {
	response := &spb.FeaturesResponse{}

	for _, feature := range request.Features {
		if h.featureProvider.Enabled(ctx, feature) {
			response.Enabled = append(response.Enabled, feature)
		}
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_FeaturesResponse{
			FeaturesResponse: response,
		},
	}
}

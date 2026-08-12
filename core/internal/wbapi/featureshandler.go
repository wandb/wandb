package wbapi

import (
	"context"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gql"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// FeaturesHandler responds to feature requests.
type FeaturesHandler struct {
	graphqlClient   graphql.Client
	featureProvider *featurechecker.FeatureProvider
}

func NewFeaturesHandler(
	graphqlClient graphql.Client,
	featureProvider *featurechecker.FeatureProvider,
) *FeaturesHandler {
	return &FeaturesHandler{
		graphqlClient:   graphqlClient,
		featureProvider: featureProvider,
	}
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
	response := &spb.OrgFeaturesResponse{
		Features: make(map[string]bool),
	}

	if len(request.GetFeatures()) == 0 {
		return &spb.ApiResponse{
			Response: &spb.ApiResponse_FeaturesResponse{
				FeaturesResponse: &spb.FeaturesResponse{
					Response: &spb.FeaturesResponse_Org{Org: response},
				},
			},
		}
	}
	if request.GetOrg() == "" {
		return apiErrorResponse(
			"org is required to check organization feature flags",
			0,
		)
	}

	result, err := gql.OrgFeatureFlags(ctx, h.graphqlClient, request.GetOrg())
	if err != nil {
		message, status := graphqlErrorInfo(err)
		return apiErrorResponse(message, status)
	}

	requested := make(map[string]struct{}, len(request.GetFeatures()))
	for _, feature := range request.GetFeatures() {
		requested[feature] = struct{}{}
	}

	if result.Organization != nil {
		for _, feature := range result.Organization.FeatureFlags {
			if feature == nil {
				continue
			}

			if _, ok := requested[feature.RampKey]; ok {
				response.Features[feature.RampKey] = feature.IsEnabled
			}
		}
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_FeaturesResponse{
			FeaturesResponse: &spb.FeaturesResponse{
				Response: &spb.FeaturesResponse_Org{Org: response},
			},
		},
	}
}

package featurechecker

import (
	"context"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ServerFeatures is responsible for providing the capabilities of a server
// Features and capabilities are retrieved from the server via a GraphQL query
type ServerFeatures struct {
	Features map[spb.ServerFeature]ServerFeature

	ctx           context.Context
	graphqlClient graphql.Client
	mu            sync.Mutex
}

type ServerFeature struct {
	DefaultValue string
	Description  string
	Enabled      bool
	Name         string
}

func NewServerFeatures(
	ctx context.Context,
	graphqlClient graphql.Client,
) *ServerFeatures {
	var features map[spb.ServerFeature]ServerFeature

	// If graphqlClient is nil, we won't ever be able to query the server
	// So create an empty map which will default to false for all features when a key is not found
	if graphqlClient == nil {
		features = make(map[spb.ServerFeature]ServerFeature)
	}

	return &ServerFeatures{
		Features:      features,
		ctx:           ctx,
		graphqlClient: graphqlClient,
		mu:            sync.Mutex{},
	}
}

func (sf *ServerFeatures) getServerFeatures() {
	sf.Features = map[spb.ServerFeature]ServerFeature{}

	// Query the server for the features provided by the server
	resp, err := gql.ServerFeaturesQuery(
		sf.ctx,
		sf.graphqlClient,
		gql.RampIDTypeUsername,
	)
	if err != nil {
		return
	}

	for _, f := range resp.ServerInfo.FeatureFlags {
		featureName := spb.ServerFeature(spb.ServerFeature_value[f.RampKey])
		sf.Features[featureName] = ServerFeature{
			Name:    f.RampKey,
			Enabled: f.IsEnabled,
		}
	}
}

func (sf *ServerFeatures) GetSingleFeature(name spb.ServerFeature) *spb.ServerFeatureItem {
	// Lazy load features if not already loaded
	if sf.Features == nil {
		sf.mu.Lock()
		// Check again after acquiring lock in case another goroutine loaded features
		if sf.Features == nil {
			sf.getServerFeatures()
		}
		sf.mu.Unlock()
	}

	// Default value, if feature is not in map
	serverFeature := &spb.ServerFeatureItem{
		Name:    name.String(),
		Enabled: false,
	}

	feature, ok := sf.Features[name]
	if ok {
		serverFeature = &spb.ServerFeatureItem{
			Name:    feature.Name,
			Enabled: feature.Enabled,
		}
	}
	return serverFeature
}

func (sf *ServerFeatures) GetMultipleFeatures(
	featureNames []spb.ServerFeature,
	logger *observability.CoreLogger,
) *spb.ServerFeatureResponse {
	// Get feature from map or default value
	features := map[int32]*spb.ServerFeatureItem{}
	for _, featureName := range featureNames {
		// Default value, if feature is not in map
		serverFeature := sf.GetSingleFeature(featureName)

		features[int32(featureName)] = serverFeature
	}

	return &spb.ServerFeatureResponse{
		Features: features,
	}
}

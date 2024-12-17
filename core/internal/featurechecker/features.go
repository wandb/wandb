package featurechecker

import (
	"context"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ServerFeaturesCache is responsible for providing the capabilities of a server
// Features and capabilities are retrieved from the server via a GraphQL query
type ServerFeaturesCache struct {
	Features map[spb.ServerFeature]Feature

	ctx           context.Context
	graphqlClient graphql.Client
	logger        *observability.CoreLogger
	once          sync.Once
}

type Feature struct {
	DefaultValue string
	Description  string
	Enabled      bool
	Name         string
}

func NewServerFeaturesCache(
	ctx context.Context,
	graphqlClient graphql.Client,
	logger *observability.CoreLogger,
) *ServerFeaturesCache {
	return &ServerFeaturesCache{
		ctx:           ctx,
		graphqlClient: graphqlClient,
		logger:        logger,
		once:          sync.Once{},
	}
}

func (sf *ServerFeaturesCache) loadFeatures() (map[spb.ServerFeature]Feature, error) {
	features := make(map[spb.ServerFeature]Feature)

	if sf.graphqlClient == nil {
		sf.logger.Warn("GraphQL client is nil, skipping feature loading")
		return features, nil
	}

	// Query the server for the features provided by the server
	resp, err := gql.ServerFeaturesQuery(sf.ctx, sf.graphqlClient, gql.RampIDTypeUsername)
	if err != nil {
		sf.logger.Error(
			"Failed to load features, feature will default to disabled",
			"error",
			err,
		)
		return features, err
	}

	for _, f := range resp.ServerInfo.FeatureFlags {
		featureName := spb.ServerFeature(spb.ServerFeature_value[f.RampKey])
		features[featureName] = Feature{
			Name:    f.RampKey,
			Enabled: f.IsEnabled,
		}
	}

	return features, nil
}

func (sf *ServerFeaturesCache) GetFeature(feature spb.ServerFeature) *spb.ServerFeatureItem {
	serverFeature := &spb.ServerFeatureItem{
		Name:    feature.String(),
		Enabled: false,
	}

	sf.once.Do(func() {
		sf.Features, _ = sf.loadFeatures()
	})

	cachedFeature, ok := sf.Features[feature]
	if !ok {
		return serverFeature
	}

	serverFeature.Enabled = cachedFeature.Enabled
	serverFeature.DefaultValue = cachedFeature.DefaultValue
	serverFeature.Description = cachedFeature.Description

	return serverFeature
}

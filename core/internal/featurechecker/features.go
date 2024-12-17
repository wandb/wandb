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
	ctx           context.Context
	features      map[spb.ServerFeature]Feature
	graphqlClient graphql.Client
	logger        *observability.CoreLogger
	once          sync.Once
}

type Feature struct {
	Enabled bool
	Name    string
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
	resp, err := gql.ServerFeaturesQuery(sf.ctx, sf.graphqlClient)
	if err != nil {
		sf.logger.Error(
			"Failed to load features, feature will default to disabled",
			"error",
			err,
		)
		return features, err
	}

	for _, f := range resp.ServerInfo.Features {
		featureName := spb.ServerFeature(spb.ServerFeature_value[f.Name])
		features[featureName] = Feature{
			Name:    f.Name,
			Enabled: f.IsEnabled,
		}
	}

	return features, nil
}

func (sf *ServerFeaturesCache) GetFeature(feature spb.ServerFeature) *Feature {
	sf.once.Do(func() {
		sf.features, _ = sf.loadFeatures()
	})

	cachedFeature, ok := sf.features[feature]
	if !ok {
		return &Feature{
			Name:    feature.String(),
			Enabled: false,
		}
	}

	return &cachedFeature
}

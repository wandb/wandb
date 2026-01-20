package featurechecker

import (
	"context"
	"sync"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ServerFeaturesCache loads optional server capabilities.
//
// Server features are loaded only once per run and then cached.
type ServerFeaturesCache struct {
	features      map[spb.ServerFeature]Feature
	graphqlClient graphql.Client
	logger        *observability.CoreLogger

	initOnce sync.Once     // used to trigger loading features in a goroutine
	initDone chan struct{} // closed after features have been loaded
}

// Feature represents a server capability that is either enabled or disabled.
//
// This is used to determine if certain functionality is available on the server,
// and gate code paths within the SDK.
type Feature struct {
	Enabled bool
	Name    string
}

func NewServerFeaturesCachePreloaded(
	features map[spb.ServerFeature]Feature,
) *ServerFeaturesCache {
	sf := &ServerFeaturesCache{
		graphqlClient: nil,
		logger:        observability.NewNoOpLogger(),
		initDone:      make(chan struct{}),
	}

	sf.initOnce.Do(func() {
		defer close(sf.initDone)
		sf.features = features
	})

	return sf
}

func NewServerFeaturesCache(
	graphqlClient graphql.Client,
	logger *observability.CoreLogger,
) *ServerFeaturesCache {
	return &ServerFeaturesCache{
		graphqlClient: graphqlClient,
		logger:        logger,
		initDone:      make(chan struct{}),
	}
}

// loadFeatures populates features and closes initDone at the end.
func (sf *ServerFeaturesCache) loadFeatures(ctx context.Context) {
	defer close(sf.initDone)
	sf.features = make(map[spb.ServerFeature]Feature)

	if sf.graphqlClient == nil {
		sf.logger.Warn(
			"featurechecker: GraphQL client is nil, skipping feature loading",
		)
		return
	}

	// Query the server for the features provided by the server
	resp, err := gql.ServerFeaturesQuery(ctx, sf.graphqlClient)
	if err != nil {
		sf.logger.Error(
			"featurechecker: failed to load features, all will be disabled",
			"error", err)
		return
	}

	for _, f := range resp.ServerInfo.Features {
		featureName := spb.ServerFeature(spb.ServerFeature_value[f.Name])
		sf.features[featureName] = Feature{
			Name:    f.Name,
			Enabled: f.IsEnabled,
		}
	}
}

func (sf *ServerFeaturesCache) GetFeature(
	ctx context.Context,
	feature spb.ServerFeature,
) *Feature {
	sf.initOnce.Do(func() { go sf.loadFeatures(ctx) })

	select {
	case <-ctx.Done():
		sf.logger.Warn(
			"featurechecker: failed to get feature",
			"name", feature.String(),
			"error", ctx.Err())
	case <-sf.initDone:
	}

	cachedFeature, ok := sf.features[feature]
	if !ok {
		return &Feature{
			Name:    feature.String(),
			Enabled: false,
		}
	}

	return &cachedFeature
}

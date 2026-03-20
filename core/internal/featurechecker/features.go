package featurechecker

import (
	"context"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// FeatureProvider fetches the values of server features.
//
// It is not guaranteed that current feature values are returned.
// Features may change at runtime, like if a server update happens,
// but callers may assume that these changes are backward compatible
// and that acting according to old feature values is okay.
//
// See the documentation on the FeaturesRequest proto for more detail.
type FeatureProvider struct {
	// semaphoreMu is a 1-buffered channel used as a mutex for loading and
	// reading features.
	//
	// A channel is used instead of an actual mutex for compatibility with
	// context cancellation. Specifically, it is necessary for this:
	//
	// 	go fp.Enabled(ctx1, feat1) // makes query with ctx1
	// 	go fp.Enabled(ctx2, feat2) // blocks while query is running
	// 	cancelCtx1() // first call fails; second call queries with ctx2
	//
	// This is not perfect (ideally the request would not be cancelled),
	// but it is an edge case and this approach is sufficient for correctness.
	semaphoreMu chan struct{}

	// boolFeatures is the state of feature flags.
	//
	// It is nil until loaded.
	boolFeatures map[spb.ServerFeature]bool

	graphqlClient graphql.Client
	logger        *observability.CoreLogger
}

func New(
	graphqlClient graphql.Client,
	logger *observability.CoreLogger,
) *FeatureProvider {
	return &FeatureProvider{
		semaphoreMu: make(chan struct{}, 1),

		graphqlClient: graphqlClient,
		logger:        logger,
	}
}

// NewPreloaded returns a feature checker with preloaded values.
//
// Used for testing.
func NewPreloaded(features map[spb.ServerFeature]bool) *FeatureProvider {
	sf := New(nil, observability.NewNoOpLogger())

	if features != nil {
		sf.boolFeatures = features
	} else {
		sf.boolFeatures = make(map[spb.ServerFeature]bool)
	}

	return sf
}

// lockedLoadFeatures queries and returns features.
func (fp *FeatureProvider) lockedLoadFeatures(ctx context.Context) {
	if fp.graphqlClient == nil {
		fp.logger.Warn(
			"featurechecker: GraphQL client is nil, skipping feature loading",
		)
		return
	}

	resp, err := gql.ServerFeaturesQuery(ctx, fp.graphqlClient)
	if err != nil {
		fp.logger.Error(
			"featurechecker: failed to load features, all will be disabled",
			"error", err)
		return
	}

	if resp.ServerInfo == nil {
		fp.logger.Error("featurechecker: response serverInfo nil")
		return
	}

	fp.boolFeatures = make(map[spb.ServerFeature]bool)
	for _, f := range resp.ServerInfo.Features {
		if f == nil {
			fp.logger.Error("featurechecker: nil feature in response")
			return
		}

		featureName := spb.ServerFeature(spb.ServerFeature_value[f.Name])
		fp.boolFeatures[featureName] = f.IsEnabled
	}
}

// Enabled returns whether a named feature is enabled.
//
// Returns false if the feature is not a boolean feature or if there is
// an error loading the feature.
func (fp *FeatureProvider) Enabled(
	ctx context.Context,
	feature spb.ServerFeature,
) bool {
	select {
	case <-ctx.Done():
		fp.logger.Warn(
			"featurechecker: failed to get feature",
			"name", feature.String(),
			"error", ctx.Err())
		return false

	case fp.semaphoreMu <- struct{}{}:
		defer func() { <-fp.semaphoreMu }()
	}

	if fp.boolFeatures == nil {
		fp.lockedLoadFeatures(ctx)
	}

	return fp.boolFeatures[feature]
}

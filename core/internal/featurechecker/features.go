package featurechecker

import (
	"context"
	"errors"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// FeatureProvider fetches server and organization feature values.
//
// It is not guaranteed that current server feature values are returned.
// Server features may change at runtime, like if a server update happens,
// but callers may assume that these changes are backward compatible
// and that acting according to old feature values is okay.
//
// See the documentation on the FeaturesRequest proto for more detail.
type FeatureProvider struct {
	// mu is a mutex implemented using a binary semaphore (1-buffered channel).
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
	mu chan struct{}

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
		mu: make(chan struct{}, 1),

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

		// Unrecognized names map to SERVER_FEATURE_UNSPECIFIED.
		feature := spb.ServerFeature(spb.ServerFeature_value[f.Name])
		if feature != spb.ServerFeature_SERVER_FEATURE_UNSPECIFIED {
			fp.boolFeatures[feature] = f.IsEnabled
		}
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

	case fp.mu <- struct{}{}:
		defer func() { <-fp.mu }()
	}

	if fp.boolFeatures == nil {
		fp.lockedLoadFeatures(ctx)
	}

	return fp.boolFeatures[feature]
}

// OrgFeatures returns requested feature values that exist for an organization.
//
// Organization feature values are not cached.
func (fp *FeatureProvider) OrgFeatures(
	ctx context.Context,
	org string,
	features []string,
) (map[string]bool, error) {
	result := make(map[string]bool)
	if len(features) == 0 {
		return result, nil
	}
	if fp.graphqlClient == nil {
		return nil, errors.New("featurechecker: GraphQL client is nil")
	}

	response, err := gql.OrgFeatureFlags(ctx, fp.graphqlClient, org)
	if err != nil {
		return nil, err
	}

	requested := make(map[string]struct{}, len(features))
	for _, feature := range features {
		requested[feature] = struct{}{}
	}

	if response.Organization != nil {
		for _, feature := range response.Organization.FeatureFlags {
			if feature == nil {
				continue
			}

			if _, ok := requested[feature.RampKey]; ok {
				result[feature.RampKey] = feature.IsEnabled
			}
		}
	}

	return result, nil
}

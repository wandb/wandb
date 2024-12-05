package server

import (
	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ServerFeatures is responsible for providing the capabilities of a server
type ServerFeatures struct {
	features map[string]ServerFeature
}

type ServerFeature struct {
	// TODO: Can we have a generic type for the default value?
	DefaultValue string
	Description  string
	Enabled      bool
	Name         string
}

func NewServerFeatures(
	graphqlClient graphql.Client,
	runWork runwork.RunWork,
	logger *observability.CoreLogger,
) *ServerFeatures {
	if graphqlClient == nil {
		return &ServerFeatures{
			features: make(map[string]ServerFeature),
		}
	}

	features := map[string]ServerFeature{}

	// Query the server for the features provided by the server
	resp, err := gql.ViewerFeatureFlags(
		runWork.BeforeEndCtx(),
		graphqlClient,
		gql.RampIDTypeUsername,
	)
	if err == nil {
		for _, f := range resp.Viewer.FeatureFlags {
			features[f.RampKey] = ServerFeature{
				Name:    f.RampKey,
				Enabled: f.IsEnabled,
				// TODO add description and default value
			}
		}
	}

	logger.Info("server features", "features", features)

	return &ServerFeatures{
		features: features,
	}
}

// TODO:
// - Add feature to map
// - remove feature from map

func (sf *ServerFeatures) GetAllFeatures() map[string]ServerFeature {
	return sf.features
}

func (sf *ServerFeatures) GetFeature(name string) *spb.ServerFeatureItem {
	// Default value, if feature is not in map
	serverFeature := &spb.ServerFeatureItem{
		Name:    name,
		Enabled: true, //false,
	}

	feature, ok := sf.features[name]
	if ok {
		serverFeature = &spb.ServerFeatureItem{
			Name:    feature.Name,
			Enabled: feature.Enabled,
		}
	}
	return serverFeature
}

func (sf *ServerFeatures) Get(
	featureNames []string,
	logger *observability.CoreLogger,
) *spb.ServerFeatureResponse {
	// Get feature from map or default value
	features := []*spb.ServerFeatureItem{}
	for _, name := range featureNames {
		// Default value, if feature is not in map
		serverFeature := sf.GetFeature(name)
		features = append(features, serverFeature)
	}

	return &spb.ServerFeatureResponse{
		Features: features,
	}
}

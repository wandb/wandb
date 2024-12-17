package featurechecker_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func stubServerFeaturesQuery(mockGQL *gqlmock.MockClient) {
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ServerFeaturesQuery"),
		`{
			"serverInfo": {
				"featureFlags": [
					{
						"rampKey": "SERVER_FEATURE_LARGE_FILENAMES",
						"isEnabled": true
					},
					{
						"rampKey": "SERVER_FEATURE_ARTIFACT_TAGS",
						"isEnabled": false
					}
				]
			}
		}`,
	)
}

func TestServerFeaturesInitialization(t *testing.T) {
	// Arrange
	mockGQL := gqlmock.NewMockClient()
	stubServerFeaturesQuery(mockGQL)
	serverFeaturesCache := featurechecker.NewServerFeaturesCache(
		context.Background(),
		mockGQL,
		observability.NewNoOpLogger(),
	)

	// Assert - features are not loaded until Get is called
	assert.Equal(t, 0, len(serverFeaturesCache.Features))

	// Act
	serverFeaturesCache.GetFeature(spb.ServerFeature_SERVER_FEATURE_LARGE_FILENAMES)

	// Assert - Features are loaded after Get is called
	assert.Equal(t, 2, len(serverFeaturesCache.Features))
	_, ok := serverFeaturesCache.Features[spb.ServerFeature_SERVER_FEATURE_LARGE_FILENAMES]
	assert.True(t, ok)
	assert.True(t, serverFeaturesCache.Features[spb.ServerFeature_SERVER_FEATURE_LARGE_FILENAMES].Enabled)
	_, ok = serverFeaturesCache.Features[spb.ServerFeature_SERVER_FEATURE_ARTIFACT_TAGS]
	assert.True(t, ok)
	assert.False(t, serverFeaturesCache.Features[spb.ServerFeature_SERVER_FEATURE_ARTIFACT_TAGS].Enabled)
}

func TestGetFeature(t *testing.T) {
	// Arrange
	mockGQL := gqlmock.NewMockClient()
	stubServerFeaturesQuery(mockGQL)
	serverFeaturesCache := featurechecker.NewServerFeaturesCache(
		context.Background(),
		mockGQL,
		observability.NewNoOpLogger(),
	)

	// Act
	enabledFeatureValue := serverFeaturesCache.GetFeature(spb.ServerFeature_SERVER_FEATURE_LARGE_FILENAMES)
	disabledFeatureValue := serverFeaturesCache.GetFeature(spb.ServerFeature_SERVER_FEATURE_ARTIFACT_TAGS)

	// Assert
	assert.True(t, enabledFeatureValue.Enabled)
	assert.False(t, disabledFeatureValue.Enabled)
	assert.Equal(t, 1, len(mockGQL.AllRequests()))
}

func TestGetFeature_MissingWithDefaultValue(t *testing.T) {
	// Arrange
	mockGQL := gqlmock.NewMockClient()
	stubServerFeaturesQuery(mockGQL)
	serverFeaturesCache := featurechecker.NewServerFeaturesCache(
		context.Background(),
		mockGQL,
		observability.NewNoOpLogger(),
	)

	// Act
	missingFeatureValue := serverFeaturesCache.GetFeature(spb.ServerFeature_SERVER_FEATURE_ARTIFACT_TAGS)

	// Assert
	assert.False(t, missingFeatureValue.Enabled)
	assert.Equal(t, 1, len(mockGQL.AllRequests()))
}

package featurechecker_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func makeServerFeatures() (*featurechecker.ServerFeatures, *gqlmock.MockClient) {
	mockGQL := gqlmock.NewMockClient()
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

	return featurechecker.NewServerFeatures(context.Background(), mockGQL), mockGQL
}

func TestServerFeaturesInitialization(t *testing.T) {
	// Arrange
	features, _ := makeServerFeatures()

	// Assert - features are not loaded until Get is called
	assert.Equal(t, 0, len(features.Features))

	// Act
	features.GetSingleFeature(spb.ServerFeature_SERVER_FEATURE_LARGE_FILENAMES)

	// Assert - Features are loaded after Get is called
	assert.Equal(t, 2, len(features.Features))
	_, ok := features.Features[spb.ServerFeature_SERVER_FEATURE_LARGE_FILENAMES]
	assert.True(t, ok)
	assert.True(t, features.Features[spb.ServerFeature_SERVER_FEATURE_LARGE_FILENAMES].Enabled)
	_, ok = features.Features[spb.ServerFeature_SERVER_FEATURE_ARTIFACT_TAGS]
	assert.True(t, ok)
	assert.False(t, features.Features[spb.ServerFeature_SERVER_FEATURE_ARTIFACT_TAGS].Enabled)
}

func TestGetFeature(t *testing.T) {
	// Arrange
	features, mockGQL := makeServerFeatures()

	// Act
	enabledFeature := features.GetSingleFeature(spb.ServerFeature_SERVER_FEATURE_LARGE_FILENAMES)
	disabledFeature := features.GetSingleFeature(spb.ServerFeature_SERVER_FEATURE_ARTIFACT_TAGS)

	// Assert
	assert.True(t, enabledFeature.Enabled)
	assert.False(t, disabledFeature.Enabled)
	assert.Equal(t, 1, len(mockGQL.AllRequests()))
}

func TestGetMultipleFeatures(t *testing.T) {
	// Arrange
	features, mockGQL := makeServerFeatures()

	// Act
	response := features.GetMultipleFeatures(
		[]spb.ServerFeature{
			spb.ServerFeature_SERVER_FEATURE_LARGE_FILENAMES,
			spb.ServerFeature_SERVER_FEATURE_ARTIFACT_TAGS,
		},
		nil,
	)

	// Assert
	assert.True(t, response.Features[int32(spb.ServerFeature_SERVER_FEATURE_LARGE_FILENAMES)].Enabled)
	assert.False(t, response.Features[int32(spb.ServerFeature_SERVER_FEATURE_ARTIFACT_TAGS)].Enabled)
	assert.Equal(t, 1, len(mockGQL.AllRequests()))
}

func TestGetFeature_MissingWithDefaultValue(t *testing.T) {
	// Arrange
	features, mockGQL := makeServerFeatures()

	// Act
	missingFeature := features.GetSingleFeature(spb.ServerFeature_SERVER_FEATURE_ARTIFACT_TAGS)

	// Assert
	assert.False(t, missingFeature.Enabled)
	assert.Equal(t, 1, len(mockGQL.AllRequests()))
}

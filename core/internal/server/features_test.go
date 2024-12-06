package server_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/server"
)

func makeServerFeatures() *server.ServerFeatures {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ServerFeaturesQuery"),
		`{
			"viewer": {
				"featureFlags": [
					{
						"rampKey": "enabled_feature",
						"isEnabled": true
					},
					{
						"rampKey": "disabled_feature",
						"isEnabled": false
					}
				]
			}
		}`,
	)

	return server.NewServerFeatures(mockGQL, nil)
}

func TestServerFeaturesInitialization(t *testing.T) {
	// Arrange
	features := makeServerFeatures()

	// Assert
	assert.Equal(t, 2, len(features.Features))
	_, ok := features.Features["enabled_feature"]
	assert.True(t, ok)
	assert.True(t, features.Features["enabled_feature"].Enabled)
	_, ok = features.Features["disabled_feature"]
	assert.True(t, ok)
	assert.False(t, features.Features["disabled_feature"].Enabled)
}

func TestGetFeature(t *testing.T) {
	// Arrange
	features := makeServerFeatures()

	// Act
	enabledFeature := features.GetFeature("enabled_feature")
	disabledFeature := features.GetFeature("disabled_feature")

	// Assert
	assert.True(t, enabledFeature.Enabled)
	assert.False(t, disabledFeature.Enabled)
}

func TestGetMultipleFeatures(t *testing.T) {
	// Arrange
	features := makeServerFeatures()

	// Act
	response := features.Get([]string{"enabled_feature", "disabled_feature"}, nil)

	// Assert
	assert.True(t, response.Features["enabled_feature"].Enabled)
	assert.False(t, response.Features["disabled_feature"].Enabled)
}

func TestGetFeature_MissingWithDefaultValue(t *testing.T) {
	// Arrange
	features := makeServerFeatures()

	// Act
	missingFeature := features.GetFeature("missing_feature")

	// Assert
	assert.False(t, missingFeature.Enabled)
}

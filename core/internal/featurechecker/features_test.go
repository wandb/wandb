package featurechecker_test

import (
	"context"
	"fmt"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func stubServerFeaturesQuery(mockGQL *gqlmock.MockClient) {
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("ServerFeaturesQuery"),
		`{
			"serverInfo": {
				"features": [
					{
						"name": "LARGE_FILENAMES",
						"isEnabled": true
					},
					{
						"name": "ARTIFACT_TAGS",
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
		mockGQL,
		observabilitytest.NewTestLogger(t),
	)

	// Assert - features are not loaded until Get is called
	assert.Equal(t, 0, len(mockGQL.AllRequests()))

	// Act
	serverFeaturesCache.GetFeature(
		context.Background(),
		spb.ServerFeature_LARGE_FILENAMES,
	)

	// Assert - Features are loaded after Get is called
	assert.Equal(t, 1, len(mockGQL.AllRequests()))
}

func TestGetFeature(t *testing.T) {
	// Arrange
	mockGQL := gqlmock.NewMockClient()
	stubServerFeaturesQuery(mockGQL)
	serverFeaturesCache := featurechecker.NewServerFeaturesCache(
		mockGQL,
		observabilitytest.NewTestLogger(t),
	)

	// Act
	enabledFeatureValue := serverFeaturesCache.GetFeature(
		context.Background(),
		spb.ServerFeature_LARGE_FILENAMES,
	)
	disabledFeatureValue := serverFeaturesCache.GetFeature(
		context.Background(),
		spb.ServerFeature_ARTIFACT_TAGS,
	)

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
		mockGQL,
		observabilitytest.NewTestLogger(t),
	)

	// Act
	missingFeatureValue := serverFeaturesCache.GetFeature(
		context.Background(),
		spb.ServerFeature_ARTIFACT_TAGS,
	)

	// Assert
	assert.False(t, missingFeatureValue.Enabled)
	assert.Equal(t, 1, len(mockGQL.AllRequests()))
}

func TestCreateFeaturesCache_WithNullGraphQLClient(t *testing.T) {
	// Arrange
	serverFeaturesCache := featurechecker.NewServerFeaturesCache(
		nil,
		observabilitytest.NewTestLogger(t),
	)

	// Act
	feature := serverFeaturesCache.GetFeature(
		context.Background(),
		spb.ServerFeature_LARGE_FILENAMES,
	)

	// Assert
	assert.False(t, feature.Enabled)
}

func TestGetFeature_GraphQLError(t *testing.T) {
	// Arrange
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchWithError(
		gqlmock.WithOpName("ServerFeaturesQuery"),
		fmt.Errorf("GraphQL Error: Internal Server Error"),
	)

	serverFeaturesCache := featurechecker.NewServerFeaturesCache(
		mockGQL,
		observabilitytest.NewTestLogger(t),
	)

	feature := serverFeaturesCache.GetFeature(
		context.Background(),
		spb.ServerFeature_LARGE_FILENAMES,
	)

	// Assert
	assert.False(t, feature.Enabled)
	assert.Equal(t, 1, len(mockGQL.AllRequests()))
}

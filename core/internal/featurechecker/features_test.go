package featurechecker_test

import (
	"context"
	"fmt"
	"testing"
	"testing/synctest"

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
						"name": "CLIENT_IDS",
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

func TestEnabled(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	stubServerFeaturesQuery(mockGQL)
	featureProvider := featurechecker.New(
		mockGQL,
		observabilitytest.NewTestLogger(t),
	)

	clientIDs := featureProvider.Enabled(
		t.Context(), spb.ServerFeature_CLIENT_IDS)
	artifactTags := featureProvider.Enabled(
		t.Context(), spb.ServerFeature_ARTIFACT_TAGS)
	largeFilenames := featureProvider.Enabled(
		t.Context(), spb.ServerFeature_LARGE_FILENAMES)

	assert.True(t, clientIDs)       // explicitly enabled
	assert.False(t, artifactTags)   // explicitly disabled
	assert.False(t, largeFilenames) // not in response
}

func TestCancellation(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		ctx1, cancel1 := context.WithCancel(t.Context())
		mockGQL := gqlmock.NewMockClient()
		featureProvider := featurechecker.New(
			mockGQL,
			observabilitytest.NewTestLogger(t),
		)

		// Hang on the first request.
		mockGQL.StubAnyHang()
		go featureProvider.Enabled(ctx1, spb.ServerFeature_CLIENT_IDS)
		synctest.Wait()

		// Make the second request, which will block while the first is hanging.
		stubServerFeaturesQuery(mockGQL) // succeed on second request
		result2 := make(chan bool)
		go func() {
			result2 <- featureProvider.Enabled(t.Context(), spb.ServerFeature_CLIENT_IDS)
		}()
		synctest.Wait()

		// Cancel the first request's context.
		cancel1()

		// Second request should make a GraphQL query with its own context.
		assert.True(t, <-result2)
	})
}

func TestNilClient(t *testing.T) {
	logger, logs := observabilitytest.NewRecordingTestLogger(t)
	featureProvider := featurechecker.New(nil, logger)

	enabled := featureProvider.Enabled(t.Context(), spb.ServerFeature_CLIENT_IDS)

	assert.False(t, enabled)
	assert.Contains(t, logs.String(), "GraphQL client is nil, skipping")
}

func TestError(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchWithError(
		gqlmock.WithOpName("ServerFeaturesQuery"),
		fmt.Errorf("GraphQL Error: Internal Server Error"),
	)
	logger, logs := observabilitytest.NewRecordingTestLogger(t)
	featureProvider := featurechecker.New(mockGQL, logger)

	enabled := featureProvider.Enabled(t.Context(), spb.ServerFeature_CLIENT_IDS)

	assert.False(t, enabled)
	assert.Contains(t, logs.String(), "GraphQL Error: Internal Server Error")
}

func TestInvalidResponse_NilServerInfo(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubAnyOnce(`{}`)
	logger, logs := observabilitytest.NewRecordingTestLogger(t)
	featureProvider := featurechecker.New(mockGQL, logger)

	enabled := featureProvider.Enabled(t.Context(), spb.ServerFeature_CLIENT_IDS)

	assert.False(t, enabled)
	assert.Contains(t, logs.String(), "response serverInfo nil")
}

func TestInvalidResponse_NilFeature(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubAnyOnce(`{ "serverInfo": { "features": [ null ] } }`)
	logger, logs := observabilitytest.NewRecordingTestLogger(t)
	featureProvider := featurechecker.New(mockGQL, logger)

	enabled := featureProvider.Enabled(t.Context(), spb.ServerFeature_CLIENT_IDS)

	assert.False(t, enabled)
	assert.Contains(t, logs.String(), "nil feature in response")
}

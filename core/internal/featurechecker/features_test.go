package featurechecker_test

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"testing/synctest"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/analyticstest"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
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

// newHTTPFeatureProvider returns a FeatureProvider that loads features over
// HTTP from a server returning the given features list.
//
// If marked, the server sets the response-origin header on its response.
func newHTTPFeatureProvider(
	t *testing.T,
	featuresJSON string,
	marked bool,
) *featurechecker.FeatureProvider {
	t.Helper()
	return newHTTPFeatureProviderWithLogger(
		t, featuresJSON, marked, observabilitytest.NewTestLogger(t))
}

// newHTTPFeatureProviderWithLogger is newHTTPFeatureProvider with a logger.
func newHTTPFeatureProviderWithLogger(
	t *testing.T,
	featuresJSON string,
	marked bool,
	logger *observability.CoreLogger,
) *featurechecker.FeatureProvider {
	t.Helper()

	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			if marked {
				w.Header().Set(api.ServerHeader, api.ServerHeaderValue)
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = fmt.Fprintf(w,
				`{"data": {"serverInfo": {"features": %s}}}`,
				featuresJSON)
		}))
	t.Cleanup(server.Close)

	httpClient := api.NewClient(api.ClientOptions{
		RetryPolicy: clients.CheckRetry,
	})
	gqlClient := graphql.NewClient(
		server.URL+"/graphql",
		api.AsStandardClient(httpClient),
	)

	return featurechecker.New(gqlClient, logger)
}

func TestResponseOriginHeader(t *testing.T) {
	const enabled = `[
		{"name": "RESPONSE_ORIGIN_HEADER", "isEnabled": true},
		{"name": "FILESTREAM_GZIP", "isEnabled": true}
	]`
	const disabled = `[
		{"name": "RESPONSE_ORIGIN_HEADER", "isEnabled": false},
		{"name": "FILESTREAM_GZIP", "isEnabled": true}
	]`
	const notListed = `[
		{"name": "FILESTREAM_GZIP", "isEnabled": true}
	]`
	// A null entry stops reading the list but keeps the features before it.
	const cutShort = `[
		{"name": "FILESTREAM_GZIP", "isEnabled": true},
		{"name": "RESPONSE_ORIGIN_HEADER", "isEnabled": true},
		null
	]`

	testCases := []struct {
		name     string
		features string
		marked   bool
		want     bool
	}{
		{"enabled and marked", enabled, true, true},
		{"enabled but response unmarked", enabled, false, false},
		{"turned off by the server's gate", disabled, true, false},
		{"old server without the feature", notListed, true, false},
		{"old server, unmarked", notListed, false, false},
		{"list cut short, marked", cutShort, true, true},
		{"list cut short, unmarked", cutShort, false, false},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			fp := newHTTPFeatureProvider(t, tc.features, tc.marked)

			got := fp.Enabled(
				t.Context(), spb.ServerFeature_RESPONSE_ORIGIN_HEADER)
			gzip := fp.Enabled(
				t.Context(), spb.ServerFeature_FILESTREAM_GZIP)

			assert.Equal(t, tc.want, got)
			assert.True(t, gzip, "other features must not change")
		})
	}
}

// An unverified header is reported so that clients behind a proxy that strips
// it can be counted. A verified one records nothing.
func TestResponseOriginHeader_UnverifiedIsReported(t *testing.T) {
	const event = "featurechecker_response_origin_header_unverified"
	const enabled = `[{"name": "RESPONSE_ORIGIN_HEADER", "isEnabled": true}]`

	for _, marked := range []bool{false, true} {
		proxy := analyticstest.NewOpenTelemetryProxyTest(t)
		logger := observability.NewCoreLogger(
			slog.New(slog.NewJSONHandler(io.Discard, nil)),
			analytics.NewTelemetryRecorder(
				proxy.OpenTelemetryProxy,
				analytics.NewTelemetryContext(),
			),
		)
		fp := newHTTPFeatureProviderWithLogger(t, enabled, marked, logger)

		_ = fp.Enabled(t.Context(), spb.ServerFeature_RESPONSE_ORIGIN_HEADER)
		require.NoError(t, proxy.Shutdown(context.Background()))

		counter, found := proxy.FindMetric(event)
		if marked {
			assert.False(t, found, "marked response must not be reported")
			continue
		}
		require.True(t, found)
		assert.EqualValues(t, 1, counter.Value)
		log, found := proxy.FindLog(event)
		require.True(t, found)
		assert.Equal(t, api.ServerHeader, log.Attributes["header"])
	}
}

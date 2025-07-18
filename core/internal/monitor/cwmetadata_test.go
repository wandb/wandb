package monitor_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	coreWeaveSampleMetadataResponse = `calico_cleanup_api:
k8s_version: v1.31
teleport_address: teleport.us-east-04.int.coreweave.com:443
teleport_region: us-east-04
org_id: b13ad0
region: us-east-04
fde_raid: true
teleport_class: compute
etc_hosts: 100.123.0.0 teleport.us-east-04.int.coreweave.com
join_token: 6r2nt2.vbt9w6s72pzcwkh7
cluster_name: cks-wb
registry_proxy_server: 100.122.0.6:3128
ca_cert_hash: 7dae4dfc5b7e430ea2d7f87776d498ec00844c06f4eacb134ea9c1d06a072761
teleport_token: a5b0f5d6645183e3b6fa3891ce66e0e8
apiserver: 100.124.0.152`
	testEndpointPath = "/test/metadata"
)

// newTestRetryableHTTPClient creates a client with no retries and a short timeout for tests.
func newTestRetryableHTTPClient(logger *observability.CoreLogger) *retryablehttp.Client {
	client := retryablehttp.NewClient()
	client.Logger = logger
	client.RetryMax = 0 // Disable retries
	client.HTTPClient.Timeout = 1 * time.Second
	return client
}

func TestCoreWeaveMetadataProbe(t *testing.T) {
	testCases := []struct {
		name                string
		setupGQLMock        func(mockGQL *gqlmock.MockClient)
		httpServerHandler   http.HandlerFunc
		expectedEnvironment *spb.EnvironmentRecord
		expectCwmError      bool // if NewCoreWeaveMetadata is expected to fail
	}{
		{
			name: "Success",
			setupGQLMock: func(mockGQL *gqlmock.MockClient) {
				mockGQL.StubMatchOnce(
					gqlmock.WithOpName("OrganizationCoreWeaveOrganizationID"),
					`{"entity":{"organization":{"coreWeaveOrganizationId":"cw1337"}}}`,
				)
			},
			httpServerHandler: func(w http.ResponseWriter, r *http.Request) {
				_, _ = w.Write([]byte(coreWeaveSampleMetadataResponse))
			},
			expectedEnvironment: &spb.EnvironmentRecord{
				Coreweave: &spb.CoreWeaveInfo{
					ClusterName: "cks-wb",
					OrgId:       "b13ad0",
					Region:      "us-east-04",
				},
			},
		},
		{
			name: "No CoreWeave Org ID from GQL",
			setupGQLMock: func(mockGQL *gqlmock.MockClient) {
				mockGQL.StubMatchOnce(
					gqlmock.WithOpName("OrganizationCoreWeaveOrganizationID"),
					`{"entity":{"organization":{"coreWeaveOrganizationId":""}}}`, // Empty Org ID
				)
			},
			httpServerHandler:   nil, // Should not be called
			expectedEnvironment: nil,
		},
		{
			name: "Nil Organization in GQL response",
			setupGQLMock: func(mockGQL *gqlmock.MockClient) {
				mockGQL.StubMatchOnce(
					gqlmock.WithOpName("OrganizationCoreWeaveOrganizationID"),
					`{"entity":{"organization": null}}`,
				)
			},
			httpServerHandler:   nil,
			expectedEnvironment: nil,
		},
		{
			name: "Nil Entity in GQL response",
			setupGQLMock: func(mockGQL *gqlmock.MockClient) {
				mockGQL.StubMatchOnce(
					gqlmock.WithOpName("OrganizationCoreWeaveOrganizationID"),
					`{"entity": null}`,
				)
			},
			httpServerHandler:   nil,
			expectedEnvironment: nil,
		},
		{
			name: "Metadata Server HTTP Error",
			setupGQLMock: func(mockGQL *gqlmock.MockClient) {
				mockGQL.StubMatchOnce(
					gqlmock.WithOpName("OrganizationCoreWeaveOrganizationID"),
					`{"entity":{"organization":{"coreWeaveOrganizationId":"cw1337"}}}`,
				)
			},
			httpServerHandler: func(w http.ResponseWriter, r *http.Request) {
				http.Error(w, "internal server error", http.StatusInternalServerError)
			},
			expectedEnvironment: nil,
		},
		{
			name: "Metadata Server Malformed Response (non key-value)",
			setupGQLMock: func(mockGQL *gqlmock.MockClient) {
				mockGQL.StubMatchOnce(
					gqlmock.WithOpName("OrganizationCoreWeaveOrganizationID"),
					`{"entity":{"organization":{"coreWeaveOrganizationId":"cw1337"}}}`,
				)
			},
			httpServerHandler: func(w http.ResponseWriter, r *http.Request) {
				_, _ = w.Write([]byte("this is not valid key:value data\nnor is this"))
			},
			expectedEnvironment: &spb.EnvironmentRecord{ // Expect empty fields as parsing will skip malformed lines
				Coreweave: &spb.CoreWeaveInfo{
					ClusterName: "",
					OrgId:       "",
					Region:      "",
				},
			},
		},
		{
			name: "Metadata Server Empty Response Body",
			setupGQLMock: func(mockGQL *gqlmock.MockClient) {
				mockGQL.StubMatchOnce(
					gqlmock.WithOpName("OrganizationCoreWeaveOrganizationID"),
					`{"entity":{"organization":{"coreWeaveOrganizationId":"cw1337"}}}`,
				)
			},
			httpServerHandler: func(w http.ResponseWriter, r *http.Request) {
				_, _ = w.Write([]byte("")) // Empty body
			},
			expectedEnvironment: &spb.EnvironmentRecord{ // Expect empty fields
				Coreweave: &spb.CoreWeaveInfo{
					ClusterName: "",
					OrgId:       "",
					Region:      "",
				},
			},
		},
		{
			name: "Metadata Server partial valid data",
			setupGQLMock: func(mockGQL *gqlmock.MockClient) {
				mockGQL.StubMatchOnce(
					gqlmock.WithOpName("OrganizationCoreWeaveOrganizationID"),
					`{"entity":{"organization":{"coreWeaveOrganizationId":"cw1337"}}}`,
				)
			},
			httpServerHandler: func(w http.ResponseWriter, r *http.Request) {
				_, _ = w.Write([]byte("cluster_name: partial-cluster\norg_id: partial-org\ninvalid line\nregion: partial-region"))
			},
			expectedEnvironment: &spb.EnvironmentRecord{
				Coreweave: &spb.CoreWeaveInfo{
					ClusterName: "partial-cluster",
					OrgId:       "partial-org",
					Region:      "partial-region",
				},
			},
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			logger := observability.NewNoOpLogger()
			mockGQLClient := gqlmock.NewMockClient()
			if tc.setupGQLMock != nil {
				tc.setupGQLMock(mockGQLClient)
			}

			s := settings.New()
			s.UpdateEntity("test-entity") // Necessary for the GQL query

			var server *httptest.Server
			if tc.httpServerHandler != nil {
				server = httptest.NewServer(http.HandlerFunc(tc.httpServerHandler))
				defer server.Close()
				s.UpdateStatsCoreWeaveMetadataBaseURL(server.URL)
				s.UpdateStatsCoreWeaveMetadataEndpoint(testEndpointPath)
			} else {
				// Provide a default valid URL even if not expecting a call,
				// to prevent NewCoreWeaveMetadata from erroring on URL parsing
				s.UpdateStatsCoreWeaveMetadataBaseURL("http://localhost:12345")
				s.UpdateStatsCoreWeaveMetadataEndpoint(testEndpointPath)
			}

			cwmParams := monitor.CoreWeaveMetadataParams{
				Client:        newTestRetryableHTTPClient(logger),
				Logger:        logger,
				GraphqlClient: mockGQLClient,
				Entity:        s.GetEntity(),
				BaseURL:       s.GetStatsCoreWeaveMetadataBaseURL(),
				Endpoint:      s.GetStatsCoreWeaveMetadataEndpoint(),
			}

			cwm, err := monitor.NewCoreWeaveMetadata(cwmParams)
			if tc.expectCwmError {
				require.Error(t, err)
				return
			}
			require.NoError(t, err)
			require.NotNil(t, cwm)

			e := cwm.Probe(context.Background())
			expectedEnvironment := tc.expectedEnvironment

			if tc.expectedEnvironment == nil {
				assert.Nil(t, e, "Probe() should return nil")
			} else {
				require.NotNil(t, e, "Probe() should not return nil")
				require.NotNil(t, e.Coreweave, "Coreweave info should not be nil")
				assert.Equal(t, expectedEnvironment.Coreweave.ClusterName, e.Coreweave.ClusterName)
				assert.Equal(t, expectedEnvironment.Coreweave.OrgId, e.Coreweave.OrgId)
				assert.Equal(t, expectedEnvironment.Coreweave.Region, e.Coreweave.Region)
			}
		})
	}
}

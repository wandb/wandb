package server

import (
	"encoding/base64"
	"log/slog"
	"net/http"

	"github.com/wandb/wandb/nexus/pkg/observability"

	"github.com/Khan/genqlient/graphql"
	"github.com/hashicorp/go-retryablehttp"
)

func basicAuth(username, password string) string {
	auth := username + ":" + password
	return base64.StdEncoding.EncodeToString([]byte(auth))
}

type authedTransport struct {
	key     string
	wrapped http.RoundTripper
}

func (t *authedTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	req.Header.Set("Authorization", "Basic "+basicAuth("api", t.key))
	req.Header.Set("User-Agent", "wandb-nexus")
	return t.wrapped.RoundTrip(req)
}

// NewRetryClient creates a new http client
func NewRetryClient(apiKey string, logger *observability.NexusLogger) *retryablehttp.Client {
	tr := &authedTransport{
		key:     apiKey,
		wrapped: http.DefaultTransport,
	}
	retryClient := retryablehttp.NewClient()
	retryClient.Logger = slog.NewLogLogger(logger.Logger.Handler(), slog.LevelDebug)
	retryClient.HTTPClient.Transport = tr
	return retryClient
}

// newGraphqlClient creates a new graphql client
func newGraphqlClient(url, apiKey string, logger *observability.NexusLogger) graphql.Client {
	retryClient := NewRetryClient(apiKey, logger)
	httpClient := retryClient.StandardClient()
	return graphql.NewClient(url, httpClient)
}

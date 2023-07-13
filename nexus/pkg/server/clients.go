package server

import (
	"encoding/base64"
	"net/http"

	"github.com/wandb/wandb/nexus/pkg/observability"

	"github.com/Khan/genqlient/graphql"
	"github.com/hashicorp/go-retryablehttp"
	"golang.org/x/exp/slog"
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
	// req.Header.Set("X-WANDB-USERNAME", "jeff")
	// req.Header.Set("X-WANDB-USER-EMAIL", "jeff@wandb.com")
	return t.wrapped.RoundTrip(req)
}

// newRetryClient creates a new http client
func newRetryClient(apiKey string, logger *observability.NexusLogger) *retryablehttp.Client {
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
	retryClient := newRetryClient(apiKey, logger)
	httpClient := retryClient.StandardClient()
	return graphql.NewClient(url, httpClient)
}

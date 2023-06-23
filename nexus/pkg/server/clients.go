package server

import (
	"encoding/base64"
	"net/http"

	"github.com/Khan/genqlient/graphql"
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

// newHttpClient creates a new http client
func newHttpClient(apiKey string) http.Client {
	httpClient := http.Client{
		Transport: &authedTransport{
			key:     apiKey,
			wrapped: http.DefaultTransport,
		},
	}
	return httpClient
}

// newGraphqlClient creates a new graphql client
func newGraphqlClient(url, apiKey string) graphql.Client {
	httpClient := http.Client{
		Transport: &authedTransport{
			key:     apiKey,
			wrapped: http.DefaultTransport,
		},
	}
	return graphql.NewClient(url, &httpClient)
}

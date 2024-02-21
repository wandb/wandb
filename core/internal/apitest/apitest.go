package apitest

import (
	"net/url"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/api"
)

// Returns a fake [Client] for testing.
func FakeClient(
	baseURLString string,
	retryableHTTP *retryablehttp.Client,
) *api.Client {
	baseURL, err := url.Parse(baseURLString)
	if err != nil {
		panic(err)
	}

	backend := api.New(baseURL)
	return backend.NewClient(retryableHTTP)
}

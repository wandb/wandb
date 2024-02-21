package api

import (
	"net/url"

	"github.com/hashicorp/go-retryablehttp"
)

// Returns a fake [Client] for testing.
func FakeClient(
	baseURLString string,
	retryableHTTP *retryablehttp.Client,
) *Client {
	baseURL, err := url.Parse(baseURLString)
	if err != nil {
		panic(err)
	}

	backend := New(baseURL)
	return backend.NewClient(retryableHTTP)
}

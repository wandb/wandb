package apitest

import (
	"net/http"
	"net/url"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/api"
)

// Returns a real [api.Client] for testing.
//
// This is a simpler API that panics on error.
func TestingClient(baseURLString string, opts api.ClientOptions) api.Client {
	baseURL, err := url.Parse(baseURLString)
	if err != nil {
		panic(err)
	}

	backend := api.New(api.BackendOptions{
		BaseURL: baseURL,
	})

	return backend.NewClient(opts)
}

// Returns a fake [api.Client] that just forwards requests.
func ForwardingClient(retryableHTTP *retryablehttp.Client) api.Client {
	return &fakeClient{retryableHTTP}
}

type fakeClient struct {
	client *retryablehttp.Client
}

func (c *fakeClient) Send(req *api.Request) (*http.Response, error) {
	retryableReq, err := retryablehttp.NewRequest(
		req.Method,
		req.Path,
		req.Body,
	)

	if err != nil {
		return nil, err
	}

	return c.client.Do(retryableReq)
}

func (c *fakeClient) Do(req *http.Request) (*http.Response, error) {
	retryableReq, err := retryablehttp.FromRequest(req)

	if err != nil {
		return nil, err
	}

	return c.client.Do(retryableReq)
}

package api

import (
	"fmt"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
)

// HTTPDoer is the interface implemented by http.Client.
type HTTPDoer interface {
	// Do is the same as http.Client.Do.
	Do(*http.Request) (*http.Response, error)
}

// AsStandardClient returns an http.Client-compatible wrapper.
//
// The wrapper passes the given http.Request to retryablehttp.FromRequest().
// Due to http.NewRequest sometimes wrapping the Body in a NopCloser,
// it can lose its Seek() method, causing FromRequest() to load it fully
// into memory.
func AsStandardClient(c RetryableClient) HTTPDoer {
	return &standardClient{c}
}

type standardClient struct{ client RetryableClient }

func (s standardClient) Do(req *http.Request) (*http.Response, error) {
	retryingReq, err := retryablehttp.FromRequest(req)
	if err != nil {
		return nil, fmt.Errorf("api: StandardClient.Do(): %v", err)
	}

	return s.client.Do(retryingReq)
}

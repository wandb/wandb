package clienttest

import (
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
)

func NewMockRetryClient(roundtripper http.RoundTripper) *retryablehttp.Client {
	retryClient := retryablehttp.NewClient()
	retryClient.HTTPClient.Transport = roundtripper
	return retryClient
}

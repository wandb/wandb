package api

import (
	"fmt"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
)

// Sends an HTTP request to the W&B backend.
func (client *Client) Send(req *Request) (*http.Response, error) {
	retryableReq, err := retryablehttp.NewRequest(
		req.Method,
		client.backend.baseURL.JoinPath(req.Path).String(),
		req.Body,
	)
	if err != nil {
		return nil, fmt.Errorf("api: failed to create request: %w", err)
	}

	for headerKey, headerValue := range req.Headers {
		retryableReq.Header.Add(headerKey, headerValue)
	}

	resp, err := client.retryableHTTP.Do(retryableReq)
	if err != nil {
		return nil, fmt.Errorf("api: failed sending: %w", err)
	}

	return resp, nil
}

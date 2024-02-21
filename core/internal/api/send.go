package api

import (
	"encoding/base64"
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
		return nil, fmt.Errorf("api: failed to create request: %v", err)
	}

	for headerKey, headerValue := range req.Headers {
		retryableReq.Header.Add(headerKey, headerValue)
	}
	client.addClientHeaders(retryableReq)
	client.addAuthHeaders(retryableReq)

	resp, err := client.retryableHTTP.Do(retryableReq)
	if err != nil {
		return nil, fmt.Errorf("api: failed sending: %v", err)
	}

	return resp, nil
}

func (client *Client) addClientHeaders(req *retryablehttp.Request) {
	for headerKey, headerValue := range client.extraHeaders {
		req.Header.Add(headerKey, headerValue)
	}
}

func (client *Client) addAuthHeaders(req *retryablehttp.Request) {
	req.Header.Add("User-Agent", "wandb-core")
	req.Header.Add(
		"Authorization",
		"Basic "+base64.StdEncoding.EncodeToString(
			[]byte("api:"+client.backend.apiKey)),
	)
}

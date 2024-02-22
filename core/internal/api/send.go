package api

import (
	"encoding/base64"
	"fmt"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
)

func (client *clientImpl) Send(req *Request) (*http.Response, error) {
	retryableReq, err := retryablehttp.NewRequest(
		req.Method,
		client.backend.baseURL.JoinPath(req.Path).String(),
		req.Body,
	)
	if err != nil {
		return nil, fmt.Errorf("api: failed to create request: %v", err)
	}

	for headerKey, headerValue := range req.Headers {
		retryableReq.Header.Set(headerKey, headerValue)
	}
	client.setClientHeaders(retryableReq)
	client.setAuthHeaders(retryableReq)

	resp, err := client.retryableHTTP.Do(retryableReq)
	if err != nil {
		return nil, fmt.Errorf("api: failed sending: %v", err)
	}

	return resp, nil
}

func (client *clientImpl) setClientHeaders(req *retryablehttp.Request) {
	for headerKey, headerValue := range client.extraHeaders {
		req.Header.Set(headerKey, headerValue)
	}
}

func (client *clientImpl) setAuthHeaders(req *retryablehttp.Request) {
	req.Header.Set("User-Agent", "wandb-core")
	req.Header.Set(
		"Authorization",
		"Basic "+base64.StdEncoding.EncodeToString(
			[]byte("api:"+client.backend.apiKey)),
	)
}

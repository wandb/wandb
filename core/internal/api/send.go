package api

import (
	"encoding/base64"
	"fmt"
	"net/http"
	"strings"

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

	// Prevent the connection from being re-used in case of an error.
	// TODO: There is an unlikely scenario when an attempt to reuse the connection
	// will result in not retrying an otherwise retryable request.
	// This is safe, however leads to a small performance hit and resource waste.
	// We are being extra cautious here, but this should be revisited.
	retryableReq.Close = true

	return client.sendToWandbBackend(retryableReq)
}

func (client *clientImpl) Do(req *http.Request) (*http.Response, error) {
	retryableReq, err := retryablehttp.FromRequest(req)
	if err != nil {
		return nil, fmt.Errorf("api: failed to parse request: %v", err)
	}

	if !client.isToWandb(req) {
		if client.backend.logger != nil {
			client.backend.logger.Warn(
				fmt.Sprintf(
					"Unexpected request through HTTP client intended for W&B: %v",
					req.URL,
				),
			)
		}

		return client.send(retryableReq)
	}

	return client.sendToWandbBackend(retryableReq)
}

// Returns whether the request would go to the W&B backend.
func (client *clientImpl) isToWandb(req *http.Request) bool {
	if req.URL.Host != client.backend.baseURL.Host {
		return false
	}

	return strings.HasPrefix(req.URL.Path, client.backend.baseURL.Path)
}

// Sends a request intended for the W&B backend.
func (client *clientImpl) sendToWandbBackend(
	req *retryablehttp.Request,
) (*http.Response, error) {
	client.setClientHeaders(req)
	client.setAuthHeaders(req)

	resp, err := client.send(req)

	// This is a bug that happens with retryablehttp sometimes.
	if err == nil && resp == nil {
		return nil, fmt.Errorf("api: nil error and nil response")
	}

	return resp, err
}

// Sends any HTTP request.
func (client *clientImpl) send(
	req *retryablehttp.Request,
) (*http.Response, error) {
	resp, err := client.retryableHTTP.Do(req)

	if err != nil {
		return nil, fmt.Errorf("api: failed sending: %v", err)
	}
	if resp == nil {
		return nil, fmt.Errorf("api: no response")
	}

	client.backend.logFinalResponseOnError(req, resp)
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

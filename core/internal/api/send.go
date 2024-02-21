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
		retryableReq.Header.Add(headerKey, headerValue)
	}

	return client.sendToWandbBackend(retryableReq)
}

func (client *clientImpl) Do(req *http.Request) (*http.Response, error) {
	retryableReq, err := retryablehttp.FromRequest(req)
	if err != nil {
		return nil, fmt.Errorf("api: failed to parse request: %v", err)
	}

	if req.URL.Host == client.backend.baseURL.Host &&
		strings.HasPrefix(req.URL.Path, client.backend.baseURL.Path) {

		return client.sendToWandbBackend(retryableReq)
	}

	return client.sendArbitrary(retryableReq)
}

func (client *clientImpl) sendToWandbBackend(
	req *retryablehttp.Request,
) (*http.Response, error) {
	client.addClientHeaders(req)
	client.addAuthHeaders(req)
	return client.sendArbitrary(req)
}

func (client *clientImpl) sendArbitrary(
	req *retryablehttp.Request,
) (*http.Response, error) {
	resp, err := client.retryableHTTP.Do(req)
	if err != nil {
		return nil, fmt.Errorf("api: failed sending: %v", err)
	}

	return resp, nil
}

func (client *clientImpl) addClientHeaders(req *retryablehttp.Request) {
	for headerKey, headerValue := range client.extraHeaders {
		req.Header.Add(headerKey, headerValue)
	}
}

func (client *clientImpl) addAuthHeaders(req *retryablehttp.Request) {
	req.Header.Add("User-Agent", "wandb-core")
	req.Header.Add(
		"Authorization",
		"Basic "+base64.StdEncoding.EncodeToString(
			[]byte("api:"+client.backend.apiKey)),
	)
}

package api

import (
	"fmt"
	"net/http"
	"strings"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/wboperation"
)

func (client *clientImpl) Do(req *retryablehttp.Request) (*http.Response, error) {
	if client.isToWandb(req) {
		return client.sendToWandbBackend(req)
	} else {
		return client.send(req)
	}
}

// Returns whether the request would go to the W&B backend.
func (client *clientImpl) isToWandb(req *retryablehttp.Request) bool {
	if req.URL.Host != client.baseURL.Host {
		return false
	}

	return strings.HasPrefix(req.URL.Path, client.baseURL.Path)
}

// Sends a request intended for the W&B backend.
func (client *clientImpl) sendToWandbBackend(
	req *retryablehttp.Request,
) (*http.Response, error) {
	err := client.credentialProvider.Apply(req.Request)
	if err != nil {
		return nil, fmt.Errorf("api: failed provide credentials for "+
			"request: %v", err)
	}

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

	wboperation.Get(req.Context()).ClearError()

	if err != nil {
		return nil, fmt.Errorf("api: failed sending: %v", err)
	}
	if resp == nil {
		return nil, fmt.Errorf("api: no response")
	}

	client.logFinalResponseOnError(req, resp)
	return resp, nil
}

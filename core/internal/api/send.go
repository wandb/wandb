package api

import (
	"fmt"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/wboperation"
)

// Do implements RetryableClient.Do.
func (client *clientImpl) Do(req *retryablehttp.Request) (*http.Response, error) {
	resp, err := client.retryableHTTP.Do(req)

	wboperation.Get(req.Context()).ClearError()

	if err != nil {
		return nil, err
	}

	// This is a bug that happens with retryablehttp sometimes.
	if resp == nil {
		return nil, fmt.Errorf("api: nil error and nil response")
	}

	client.logFinalResponseOnError(req, resp)
	return resp, nil
}

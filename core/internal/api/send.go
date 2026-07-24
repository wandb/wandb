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

	if err != nil {
		// Keep the operation's error status: it identifies the error that
		// was being retried, which is usually more specific than the final
		// error. In particular, when the request is cancelled by a deadline
		// during a retry backoff, `err` is a bare context error.
		return nil, err
	}

	wboperation.Get(req.Context()).ClearError()

	// This is a bug that happens with retryablehttp sometimes.
	if resp == nil {
		return nil, fmt.Errorf("api: nil error and nil response")
	}

	client.logFinalResponseOnError(req, resp)
	return resp, nil
}

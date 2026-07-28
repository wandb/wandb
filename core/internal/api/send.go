package api

import (
	"context"
	"errors"
	"fmt"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/wboperation"
)

// Do implements RetryableClient.Do.
func (client *clientImpl) Do(req *retryablehttp.Request) (*http.Response, error) {
	// Track retried errors to provide a better error message at the end.
	req = req.WithContext(withRetryObserver(req.Context()))

	resp, err := client.retryableHTTP.Do(req)
	wboperation.Get(req.Context()).ClearError()

	if err != nil {
		return nil, enhanceContextError(err, lastRetriedError(req.Context()))
	}

	// This is a bug that happens with retryablehttp sometimes.
	if resp == nil {
		return nil, fmt.Errorf("api: nil error and nil response")
	}

	client.logFinalResponseOnError(req, resp)
	return resp, nil
}

// enhanceContextError adds the message of the most recently retried error
// to context cancellation and timeout errors.
func enhanceContextError(finalErr error, lastRetriedErr string) error {
	if lastRetriedErr == "" {
		return finalErr
	}

	if !errors.Is(finalErr, context.Canceled) &&
		!errors.Is(finalErr, context.DeadlineExceeded) {
		return finalErr
	}

	// Use Join to preserve the fact that this is a cancellation or timeout,
	// so that callers can check it.
	return errors.Join(
		finalErr,
		fmt.Errorf("last status: %s", lastRetriedErr),
	)
}

package filestream

import (
	"context"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
)

// RetryPolicy is the retry policy to be used for file stream operations.
func RetryPolicy(
	ctx context.Context,
	resp *http.Response,
	err error,
) (bool, error) {

	// non-retryable status codes
	statusCode := resp.StatusCode
	switch {
	case statusCode == http.StatusBadRequest: // don't retry on 400 bad request or 409 conflict
		return false, err
	case statusCode == http.StatusUnauthorized: // don't retry on 401 unauthorized
		return false, err
	case statusCode == http.StatusForbidden: // don't retry on 403 forbidden
		return false, err
	case statusCode == http.StatusNotFound: // don't retry on 404 not found
		return false, err
	case statusCode == http.StatusConflict: // don't retry on 409 conflict
		return false, err
	case statusCode == http.StatusGone: // don't retry on 410 Gone
		return false, err
	}
	// if err != nil, retryablehttp's base policy is to retry
	// if the error is recoverable, meaning it's not:
	//   - due to too many redirects.
	//   - due to an invalid protocol scheme.
	//   - due to an invalid header.
	//   - due to TLS cert verification failure.
	shoudRetry, err := retryablehttp.ErrorPropagatedRetryPolicy(ctx, resp, err)
	// if resp != nil and err == nil, retryablehttp's base policy is to retry
	// if the status code is 429, 5xx, or invalid. We want to be extra cautious
	// and retry in other remaining cases as well.
	if !shoudRetry && err == nil {
		return true, nil
	}
	return shoudRetry, err
}

package filestream

import (
	"context"
	"net/http"
	"time"

	"github.com/hashicorp/go-retryablehttp"
)

const (
	// Retry filestream requests for 7 days before dropping chunk
	// retry_count = seconds_in_7_days / max_retry_time + num_retries_until_max_60_sec
	//             = 7 * 86400 / 60 + ceil(log2(60/2))
	//             = 10080 + 5
	DefaultRetryMax     = 10085
	DefaultRetryWaitMin = 2 * time.Second
	DefaultRetryWaitMax = 60 * time.Second
	// A 3-minute timeout for all filestream post requests
	DefaultNonRetryTimeout = 180 * time.Second
)

// RetryPolicy is the retry policy to be used for file stream operations.
//
// The policy is to retry by default, unless we know an error is not retryable.
func RetryPolicy(
	ctx context.Context,
	resp *http.Response,
	err error,
) (bool, error) {
	// Respect context cancellation and deadlines.
	if ctx.Err() != nil {
		return false, ctx.Err()
	}

	// Use retryablehttp's defaults for errors.
	//
	// Go's http package sometimes returns errors that are retryable rather
	// than retrying them itself, such as https://github.com/golang/go/issues/4677
	// That issue is closed, but we encountered what seems to be the same error
	// in 2024.
	//
	// retryablehttp retries errors by default, with exceptions for known
	// non-retryable errors, for which it has to use regexp matching on the
	// error string (ugh!).
	if err != nil {
		return retryablehttp.DefaultRetryPolicy(ctx, resp, err)
	}

	// Avoid retrying specific status codes.
	switch resp.StatusCode {
	case http.StatusBadRequest: // don't retry on 400 bad request
		return false, nil
	case http.StatusUnauthorized: // don't retry on 401 unauthorized
		return false, nil
	case http.StatusForbidden: // don't retry on 403 forbidden
		return false, nil
	case http.StatusNotFound: // don't retry on 404 not found
		return false, nil
	case http.StatusConflict: // don't retry on 409 conflict
		return false, nil
	case http.StatusGone: // don't retry on 410 Gone
		return false, nil
	case http.StatusRequestEntityTooLarge: // don't retry on 413 Content Too Large
		return false, nil
	case http.StatusUnprocessableEntity: // don't retry on 422 Unprocessable Content
		return false, nil
	case http.StatusNotImplemented: // don't retry on 501 not implemented
		return false, nil
	}

	// Retry some invalid HTTP codes.
	if resp.StatusCode == 0 || resp.StatusCode >= 600 {
		return true, nil
	}

	// Retry any other client or server errors.
	return resp.StatusCode >= 400 && resp.StatusCode <= 599, nil
}

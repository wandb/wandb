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
func RetryPolicy(
	ctx context.Context,
	resp *http.Response,
	err error,
) (bool, error) {
	// non-retryable status codes
	if resp != nil {
		switch resp.StatusCode {
		case http.StatusBadRequest: // don't retry on 400 bad request or 409 conflict
			return false, err
		case http.StatusUnauthorized: // don't retry on 401 unauthorized
			return false, err
		case http.StatusForbidden: // don't retry on 403 forbidden
			return false, err
		case http.StatusNotFound: // don't retry on 404 not found
			return false, err
		case http.StatusConflict: // don't retry on 409 conflict
			return false, err
		case http.StatusGone: // don't retry on 410 Gone
			return false, err
		}
	}
	// if err != nil, retryablehttp's base policy is to retry
	// if the error is recoverable, meaning it's not:
	//   - due to too many redirects.
	//   - due to an invalid protocol scheme.
	//   - due to an invalid header.
	//   - due to TLS cert verification failure.
	// if resp != nil and err == nil, retryablehttp's base policy is to retry
	// if the status code is 429, 5xx, or invalid. We want to be extra cautious
	// and retry in other remaining cases as well.
	// TODO: consider moving this logic from the retryablehttp package to here.
	return retryablehttp.ErrorPropagatedRetryPolicy(ctx, resp, err)
}

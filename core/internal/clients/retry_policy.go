package clients

import (
	"context"
	"errors"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
)

type ContextKey string

const CtxRetryPolicyKey ContextKey = "retryFunc"

// PermanentError is implemented by errors that no amount of retrying can
// resolve, like a credential exchange the server definitively rejected.
type PermanentError interface {
	error

	// PermanentError returns true if retrying the request cannot succeed.
	PermanentError() bool
}

// isPermanent returns true if the error chain contains a PermanentError.
func isPermanent(err error) bool {
	var perm PermanentError
	return errors.As(err, &perm) && perm.PermanentError()
}

// RetryMostFailures is a retry policy that retries most client (4xx) errors,
// server (5xx) errors, and connection problems.
func RetryMostFailures(
	ctx context.Context,
	resp *http.Response,
	err error,
) (bool, error) {
	// Respect context cancellation and deadlines.
	if ctx.Err() != nil {
		return false, ctx.Err()
	}

	if err != nil {
		// Errors marked permanent cannot be resolved by retrying, like a
		// failed credential exchange with a definitive server response.
		if isPermanent(err) {
			return false, err
		}

		// Use retryablehttp's defaults for other errors.
		//
		// Most errors are retryable, but a few are not. Unfortunately, the
		// only way to detect them is to match on the error string. We let
		// retryablehttp do this for us.
		//
		// Retryable errors are often connection issues. Non-retryable errors
		// include invalid usage, TLS verification problems, and too many
		// redirects.
		return retryablehttp.DefaultRetryPolicy(ctx, resp, err)
	}

	return RetryableStatus(resp.StatusCode), nil
}

// RetryableStatus reports whether a request that returned the given HTTP
// status may succeed if retried.
//
// This is the status classification behind RetryMostFailures: most client
// (4xx) and server (5xx) errors are retryable, except those that mean the
// request itself can never succeed.
func RetryableStatus(statusCode int) bool {
	switch statusCode {
	case http.StatusBadRequest, // 400
		http.StatusUnauthorized,          // 401
		http.StatusPaymentRequired,       // 402
		http.StatusForbidden,             // 403
		http.StatusNotFound,              // 404
		http.StatusConflict,              // 409
		http.StatusGone,                  // 410
		http.StatusRequestEntityTooLarge, // 413
		http.StatusUnprocessableEntity,   // 422
		http.StatusNotImplemented:        // 501
		return false
	}

	// Retry some invalid HTTP codes.
	if statusCode == 0 || statusCode >= 600 {
		return true
	}

	// Retry any other client or server errors.
	return statusCode >= 400 && statusCode <= 599
}

func UpsertBucketRetryPolicy(ctx context.Context, resp *http.Response, err error) (bool, error) {
	statusCode := resp.StatusCode
	switch statusCode {
	case http.StatusGone: // don't retry on 410 Gone
		return false, err
	case http.StatusConflict: // retry on 409 Conflict
		return true, err
	case http.StatusBadRequest: // don't retry on 400 bad request
		return false, err
	case http.StatusUnprocessableEntity:
		return false, err
	default: // use default retry policy for all other status codes
		return RetryMostFailures(ctx, resp, err)
	}
}

func CheckRetry(ctx context.Context, resp *http.Response, err error) (bool, error) {
	if err != nil || ctx.Err() != nil {
		// Errors marked permanent cannot be resolved by retrying, like a
		// failed credential exchange with a definitive server response.
		if isPermanent(err) {
			return false, err
		}

		return retryablehttp.DefaultRetryPolicy(ctx, resp, err)
	}

	// get retry policy from context
	retryPolicy, ok := ctx.Value(CtxRetryPolicyKey).(func(context.Context, *http.Response, error) (bool, error))
	switch {
	case !ok, retryPolicy == nil:
		return RetryMostFailures(ctx, resp, err)
	default:
		return retryPolicy(ctx, resp, err)
	}
}

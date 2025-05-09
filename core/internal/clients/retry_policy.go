package clients

import (
	"context"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
)

type ContextKey string

const CtxRetryPolicyKey ContextKey = "retryFunc"

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

	// Use retryablehttp's defaults for errors.
	//
	// Most errors are retryable, but a few are not. Unfortunately, the only
	// way to detect them is to match on the error string. We let retryablehttp
	// do this for us.
	//
	// Retryable errors are often connection issues. Non-retryable errors
	// include invalid usage, TLS verification problems, and too many redirects.
	if err != nil {
		return retryablehttp.DefaultRetryPolicy(ctx, resp, err)
	}

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

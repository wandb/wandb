package clients

import (
	"context"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
)

type ContextKey string

const CtxRetryPolicyKey ContextKey = "retryFunc"

func DefaultRetryPolicy(ctx context.Context, resp *http.Response, err error) (bool, error) {
	statusCode := resp.StatusCode
	switch {
	case statusCode == http.StatusBadRequest: // don't retry on 400 bad request
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
	case statusCode >= 400 && statusCode < 500: // TODO: ideally we should only retry on 429
		return true, err
	default: // use default retry policy for all other status codes
		return retryablehttp.DefaultRetryPolicy(ctx, resp, err)
	}
}

func UpsertBucketRetryPolicy(ctx context.Context, resp *http.Response, err error) (bool, error) {
	statusCode := resp.StatusCode
	switch {
	case statusCode == http.StatusGone: // don't retry on 410 Gone
		return false, err
	case statusCode == http.StatusConflict: // retry on 409 Conflict
		return true, err
	case statusCode == http.StatusBadRequest: // don't retry on 400 bad request
		return false, err
	case statusCode == http.StatusUnprocessableEntity:
		return false, err
	default: // use default retry policy for all other status codes
		return DefaultRetryPolicy(ctx, resp, err)
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
		return DefaultRetryPolicy(ctx, resp, err)
	default:
		return retryPolicy(ctx, resp, err)
	}
}

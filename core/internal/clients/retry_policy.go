package clients

import (
	"context"
	"fmt"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
)

type ContextKey string

const CtxRetryPolicyKey ContextKey = "retryFunc"

func DefaultRetryPolicy(ctx context.Context, resp *http.Response, err error) (bool, error) {
	statusCode := resp.StatusCode
	switch {
	case statusCode == http.StatusBadRequest, statusCode == http.StatusConflict: // don't retry on 400 bad request or 409 conflict
		return false, fmt.Errorf("the server responded with an error. (Error %d: %s)", statusCode, http.StatusText(statusCode))
	case statusCode == http.StatusUnauthorized: // don't retry on 401 unauthorized
		return false, fmt.Errorf("the API key you provided is either invalid or missing. (Error %d: %s)", statusCode, http.StatusText(statusCode))
	case statusCode == http.StatusForbidden: // don't retry on 403 forbidden
		return false, fmt.Errorf("you don't have permission to access this resource. (Error %d: %s)", statusCode, http.StatusText(statusCode))
	case statusCode == http.StatusNotFound: // don't retry on 404 not found
		return false, fmt.Errorf("the resource you requested could not be found. (Error %d: %s)", statusCode, http.StatusText(statusCode))
	case statusCode >= 400 && statusCode < 500: // retry on 4xx client error
		return true, fmt.Errorf("the server responded with an error. (Error %d: %s)", statusCode, http.StatusText(statusCode))
	default: // use default retry policy for all other status codes
		return retryablehttp.DefaultRetryPolicy(ctx, resp, err)
	}
}

func UpsertBucketRetryPolicy(ctx context.Context, resp *http.Response, err error) (bool, error) {
	statusCode := resp.StatusCode
	// internalError := false
	// body, err := io.ReadAll(resp.Body)
	// if err == nil {
	// 	// check "errors" field in body and whether its length is > 0
	// 	var bodyMap interface{}
	// 	err = json.Unmarshal(body, &bodyMap)
	// 	if ok := bodyMap.(map[string]interface{})["errors"]; ok != nil {
	// 		fmt.Println("errors", ok)
	// 		if len(ok.([]interface{})) > 0 {
	// 			internalError = true
	// 		}
	// 	}
	// }
	switch {
	case statusCode == http.StatusGone: // don't retry on 410 Gone
		return false, fmt.Errorf("the server responded with an error. (Error %d: %s)", statusCode, http.StatusText(statusCode))
	case statusCode == http.StatusConflict: // retry on 409 Conflict
		return true, fmt.Errorf("conflict, retrying. (Error %d: %s)", statusCode, http.StatusText(statusCode))
	// case statusCode == 200 && internalError: // retry on 200 OK with internal error
	// 	return true, fmt.Errorf("internal error, retrying. (Error %d: %s)", statusCode, http.StatusText(statusCode))
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

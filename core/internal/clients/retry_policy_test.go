package clients_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/clients"
)

func TestDefaultRetryPolicy(t *testing.T) {
	testCases := []struct {
		name        string
		statusCode  int
		shouldRetry bool
		errMsg      string
	}{
		{"BadRequest", http.StatusBadRequest, false, "the server responded with an error. (Error 400: Bad Request)"},
		{"Conflict", http.StatusConflict, false, "the server responded with an error. (Error 409: Conflict)"},
		{"Unauthorized", http.StatusUnauthorized, false, "the API key you provided is either invalid or missing. (Error 401: Unauthorized)"},
		{"Forbidden", http.StatusForbidden, false, "you don't have permission to access this resource. (Error 403: Forbidden)"},
		{"NotFound", http.StatusNotFound, false, "the resource you requested could not be found. (Error 404: Not Found)"},
		{"Other4xxError", http.StatusTeapot, true, "the server responded with an error. (Error 418: I'm a teapot)"},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			resp := httptest.NewRecorder().Result()
			resp.StatusCode = tc.statusCode

			retry, err := clients.DefaultRetryPolicy(context.Background(), resp, nil)

			assert.Equal(t, tc.shouldRetry, retry)
			if err != nil {
				assert.Equal(t, tc.errMsg, err.Error())
			}
		})
	}
}

func TestUpsertBucketRetryPolicy(t *testing.T) {
	testCases := []struct {
		name        string
		statusCode  int
		shouldRetry bool
		errMsg      string
	}{
		{"Gone", http.StatusGone, false, "the server responded with an error. (Error 410: Gone)"},
		{"Conflict", http.StatusConflict, true, "conflict, retrying. (Error 409: Conflict)"},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			resp := httptest.NewRecorder().Result()
			resp.StatusCode = tc.statusCode

			retry, err := clients.UpsertBucketRetryPolicy(context.Background(), resp, nil)

			assert.Equal(t, tc.shouldRetry, retry)
			if err != nil {
				assert.Equal(t, tc.errMsg, err.Error())
			}
		})
	}
}

func TestCheckRetry(t *testing.T) {
	// Mock a retry policy
	mockRetryPolicy := func(ctx context.Context, resp *http.Response, err error) (bool, error) {
		if resp.StatusCode == http.StatusForbidden {
			return true, nil
		}
		return false, fmt.Errorf("default error")
	}

	ctx := context.WithValue(context.Background(), clients.CtxRetryPolicyKey, mockRetryPolicy)
	resp := httptest.NewRecorder().Result()

	resp.StatusCode = http.StatusForbidden
	retry, err := clients.CheckRetry(ctx, resp, nil)
	assert.True(t, retry)
	assert.Nil(t, err)

	resp.StatusCode = http.StatusNotFound
	retry, err = clients.CheckRetry(ctx, resp, nil)
	assert.False(t, retry)
	assert.Error(t, err)

	// Test with no policy in context
	ctx = context.Background()
	resp.StatusCode = http.StatusNotFound
	retry, err = clients.CheckRetry(ctx, resp, nil)
	assert.False(t, retry)
	assert.NoError(t, err)
}

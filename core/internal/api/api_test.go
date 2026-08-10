package api_test

import (
	"bytes"
	"context"
	"net/http"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/httplayers"
)

func TestDo(t *testing.T) {
	server := apitest.NewRecordingServer()
	defer server.Close()

	client := api.NewClient(api.ClientOptions{
		PreRetryLayers: httplayers.DefaultHeaders(http.Header{
			"ClientHeader": []string{"xyz"},
		}),
	})

	testRequest, err := retryablehttp.NewRequest(
		http.MethodGet,
		server.URL+"/wandb/some/test/path",
		bytes.NewReader([]byte("my test request")),
	)
	require.NoError(t, err)
	testRequest.Header.Set("Header1", "one")
	testRequest.Header.Set("Header2", "two")

	_, err = client.Do(testRequest)
	require.NoError(t, err)

	allRequests := server.Requests()
	require.Len(t, allRequests, 1)

	req := allRequests[0]
	assert.Equal(t, http.MethodGet, req.Method)
	assert.Equal(t, "/wandb/some/test/path", req.URL.Path)
	assert.Equal(t, "my test request", string(req.Body))
	assert.Equal(t, "one", req.Header.Get("Header1"))
	assert.Equal(t, "two", req.Header.Get("Header2"))
	assert.Equal(t, "xyz", req.Header.Get("ClientHeader"))
	assert.Equal(t, "wandb-core", req.Header.Get("User-Agent"))
}

func TestRetryTimeout(t *testing.T) {
	// This test would benefit from synctest, but httptest does not currently
	// support that. It will with httptest.NewTestServer() in go 1.27.0.
	// https://github.com/golang/go/issues/76608

	// A client that retries many times, and a server that always fails.
	client := api.NewClient(api.ClientOptions{
		RetryMax: 1,
		// After the first attempt, block to let the request time out.
		RetryWaitMin: 1 * time.Minute,
		RetryWaitMax: 1 * time.Minute,
	})
	server := apitest.NewRecordingServer(
		apitest.WithHandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusInternalServerError)
			_, _ = w.Write([]byte("test error"))
		}),
	)
	defer server.Close()

	// A request that'll time out after half a second.
	ctx, cancel := context.WithTimeout(t.Context(), 500*time.Millisecond)
	defer cancel()
	request, err := retryablehttp.NewRequestWithContext(
		ctx,
		http.MethodGet,
		server.URL,
		http.NoBody,
	)
	require.NoError(t, err)

	// Make the request, it should time out. We expect exactly one attempt
	// to have gone through before the timeout.
	response, err := client.Do(request)

	assert.Nil(t, response)
	var retryError *api.RetryError
	require.ErrorAs(t, err, &retryError)
	assert.ErrorIs(t, retryError.Inner, context.DeadlineExceeded)
	assert.Equal(t, "HTTP 500: test error", retryError.LastStatus)
}

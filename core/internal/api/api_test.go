package api_test

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/httplayers"
	"github.com/wandb/wandb/core/internal/observabilitytest"
)

func TestDo(t *testing.T) {
	server := apitest.NewRecordingServer()
	defer server.Close()

	client := api.NewClient(api.ClientOptions{
		PreRetryLayers: httplayers.ExtraHeaders(http.Header{
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
	assert.Len(t, allRequests, 1)

	req := allRequests[0]
	assert.Equal(t, http.MethodGet, req.Method)
	assert.Equal(t, "/wandb/some/test/path", req.URL.Path)
	assert.Equal(t, "my test request", string(req.Body))
	assert.Equal(t, "one", req.Header.Get("Header1"))
	assert.Equal(t, "two", req.Header.Get("Header2"))
	assert.Equal(t, "xyz", req.Header.Get("ClientHeader"))
	assert.Equal(t, "wandb-core", req.Header.Get("User-Agent"))
}

func TestNewClientWithProxy(t *testing.T) {
	proxyURL := ""
	testServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxyURL = r.Host // Capture the proxy URL
		if r.Host != proxyURL {
			t.Errorf("expected request to go through proxy, but got %s", r.URL.Host)
		}
	}))
	defer testServer.Close()

	proxyParsedURL, _ := url.Parse(testServer.URL)

	clientOptions := api.ClientOptions{
		RetryMax:        5,
		RetryWaitMin:    1 * time.Second,
		RetryWaitMax:    5 * time.Second,
		NonRetryTimeout: api.DefaultNonRetryTimeout,
		ProxyConnectHeader: http.Header{
			"Proxy-Authorization": []string{"Basic dXNlcjpwYXNz"},
		},
		Proxy: func(req *http.Request) (*url.URL, error) {
			return proxyParsedURL, nil
		},

		Logger: observabilitytest.NewTestLogger(t).Logger,
	}

	client := api.NewClient(clientOptions)

	// Create a test request
	testReq, err := retryablehttp.NewRequest("GET", "http://api.example.com/test", nil)
	if err != nil {
		t.Fatalf("failed to create test request: %v", err)
	}

	resp, err := client.Do(testReq)
	if err != nil {
		t.Fatalf("failed to do test request: %v", err)
	}
	defer func() {
		_ = resp.Body.Close()
	}()

	// Check that Proxy-Authorization header is set
	proxyReqHeader := resp.Request.Header.Get("Proxy-Authorization")
	assert.Equal(t, "Basic dXNlcjpwYXNz", proxyReqHeader)
}

func TestNewClientWithRetry(t *testing.T) {
	serverCallCount := 0
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			serverCallCount++
			if serverCallCount == 1 {
				// induce a retry by returning a 500 error
				w.WriteHeader(http.StatusInternalServerError)
				_, _ = w.Write([]byte("Internal Server Error"))
				return
			}
			_, _ = w.Write([]byte("OK"))
		}),
	)

	serverURL := server.URL + "/wandb"

	retryCallCount := 0
	client := api.NewClient(api.ClientOptions{
		RetryPolicy: func(ctx context.Context, resp *http.Response, err error) (bool, error) {
			if resp.StatusCode == http.StatusInternalServerError {
				return true, nil
			}
			return false, nil
		},
		RetryMax: 2,
		PrepareRetry: func(req *http.Request) error {
			retryCallCount++
			return nil
		},
	})

	// Create a test request
	testReq, err := retryablehttp.NewRequest("GET", serverURL, nil)
	require.NoError(t, err)
	resp, err := client.Do(testReq)
	require.NoError(t, err)
	defer func() {
		_ = resp.Body.Close()
	}()

	assert.Equal(t, 1, retryCallCount)
	assert.Equal(t, 2, serverCallCount)
}

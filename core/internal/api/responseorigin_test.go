package api_test

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
)

func TestHasServerHeader(t *testing.T) {
	marked := &http.Response{Header: http.Header{}}
	marked.Header.Set(api.ServerHeader, api.ServerHeaderValue)
	otherValue := &http.Response{Header: http.Header{}}
	otherValue.Header.Set(api.ServerHeader, "proxy")

	assert.True(t, api.HasServerHeader(marked))
	assert.False(t, api.HasServerHeader(otherValue))
	assert.False(t, api.HasServerHeader(&http.Response{Header: http.Header{}}))
	assert.False(t, api.HasServerHeader(nil))
}

func TestWithResponseObserver_SeesFinalResponseOnly(t *testing.T) {
	attempts := 0
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			attempts++
			if attempts == 1 {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			w.Header().Set(api.ServerHeader, api.ServerHeaderValue)
			w.WriteHeader(http.StatusOK)
		}))
	defer server.Close()
	client := api.NewClient(api.ClientOptions{
		RetryPolicy:  clients.RetryMostFailures,
		RetryMax:     1,
		RetryWaitMin: time.Millisecond,
		RetryWaitMax: time.Millisecond,
	})

	var observed []*http.Response
	ctx := api.WithResponseObserver(t.Context(), func(resp *http.Response) {
		observed = append(observed, resp)
	})
	req, err := retryablehttp.NewRequestWithContext(
		ctx, http.MethodGet, server.URL, nil)
	require.NoError(t, err)
	resp, err := client.Do(req)
	require.NoError(t, err)
	_ = resp.Body.Close()

	require.Len(t, observed, 1)
	assert.Equal(t, http.StatusOK, observed[0].StatusCode)
	assert.True(t, api.HasServerHeader(observed[0]))
}

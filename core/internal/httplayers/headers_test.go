package httplayers_test

import (
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/httplayers"
)

func TestExtraHeaders_AddsMissingHeaders(t *testing.T) {
	req, err := http.NewRequest(http.MethodGet, "https://example.com", http.NoBody)
	require.NoError(t, err)
	req.Header = nil

	wrapped := httplayers.ExtraHeaders(http.Header{
		"X-EXTRA-HEADER": []string{"extra-header-value"},
	}).WrapHTTP(func(req *http.Request) (*http.Response, error) {
		assert.Equal(t, "extra-header-value", req.Header.Get("X-EXTRA-HEADER"))
		return &http.Response{StatusCode: http.StatusOK}, nil
	})

	_, err = wrapped(req)
	require.NoError(t, err)
}

func TestExtraHeaders_PreservesExistingHeaders(t *testing.T) {
	req, err := http.NewRequest(http.MethodGet, "https://example.com", http.NoBody)
	require.NoError(t, err)
	req.Header.Set("Authorization", "extra-request-authorization")
	req.Header.Set("User-Agent", "extra-request-user-agent")

	wrapped := httplayers.ExtraHeaders(http.Header{
		"Authorization":  []string{"extra-authorization-value"},
		"User-Agent":     []string{"extra-user-agent"},
		"X-EXTRA-HEADER": []string{"extra-header-value"},
	}).WrapHTTP(func(req *http.Request) (*http.Response, error) {
		assert.Equal(t, "extra-request-authorization", req.Header.Get("Authorization"))
		assert.Equal(t, "extra-request-user-agent", req.Header.Get("User-Agent"))
		assert.Equal(t, "extra-header-value", req.Header.Get("X-EXTRA-HEADER"))
		return &http.Response{StatusCode: http.StatusOK}, nil
	})

	_, err = wrapped(req)
	require.NoError(t, err)
}

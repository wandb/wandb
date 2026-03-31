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
	req.Header.Set("Authorization", "request-authorization")
	req.Header.Set("NOT-CASE-SENSITIVE", "request-value")

	wrapped := httplayers.ExtraHeaders(http.Header{
		"Authorization":      []string{"extra-authorization-value"},
		"X-EXTRA-HEADER":     []string{"extra-header-value"},
		"not-case-sensitive": []string{"extra-value"},
	}).WrapHTTP(func(req *http.Request) (*http.Response, error) {
		assert.Equal(t, "request-authorization", req.Header.Get("Authorization"))
		assert.Equal(t, "extra-header-value", req.Header.Get("X-EXTRA-HEADER"))
		assert.Equal(t, "request-value", req.Header.Get("NOT-CASE-SENSITIVE"))
		return &http.Response{StatusCode: http.StatusOK}, nil
	})

	_, err = wrapped(req)
	require.NoError(t, err)
}

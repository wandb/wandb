package httplayers_test

import (
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/httplayers"
)

// newHeader normalzie header like caller (api client) does.
func newHeader(m map[string]string) http.Header {
	h := make(http.Header)
	for k, v := range m {
		h.Set(k, v)
	}
	return h
}

func TestExtraHeaders_AddsMissingHeaders(t *testing.T) {
	req, err := http.NewRequest(http.MethodGet, "https://example.com", http.NoBody)
	require.NoError(t, err)
	req.Header = nil

	wrapped := httplayers.ExtraHeaders(newHeader(map[string]string{
		"X-EXTRA-HEADER": "extra-header-value",
	})).WrapHTTP(func(req *http.Request) (*http.Response, error) {
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

	wrapped := httplayers.ExtraHeaders(newHeader(map[string]string{
		"Authorization":      "extra-authorization-value",
		"X-EXTRA-HEADER":     "extra-header-value",
		"not-case-sensitive": "extra-value",
	})).WrapHTTP(func(req *http.Request) (*http.Response, error) {
		assert.Equal(t, "request-authorization", req.Header.Get("Authorization"))
		assert.Equal(t, "extra-header-value", req.Header.Get("X-EXTRA-HEADER"))
		assert.Equal(t, "request-value", req.Header.Get("NOT-CASE-SENSITIVE"))
		return &http.Response{StatusCode: http.StatusOK}, nil
	})

	_, err = wrapped(req)
	require.NoError(t, err)
}

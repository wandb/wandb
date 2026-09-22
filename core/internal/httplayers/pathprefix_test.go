package httplayers_test

import (
	"net/http"
	"net/url"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/httplayers"
	"github.com/wandb/wandb/core/internal/httplayerstest"
)

func TestPrefixPath(t *testing.T) {
	testCases := []struct {
		name       string
		baseURL    string
		requestURL string
		expected   string
	}{
		{"prefixes same-origin path outside base",
			"https://forge/api/wandb",
			"https://forge/files/e/p/r/x%20y.txt?a=1",
			"https://forge/api/wandb/files/e/p/r/x%20y.txt?a=1"},
		{"leaves path under base alone",
			"https://forge/api/wandb",
			"https://forge/api/wandb/graphql",
			"https://forge/api/wandb/graphql"},
		{"leaves other host alone",
			"https://forge/api/wandb",
			"https://storage.googleapis.com/files/x",
			"https://storage.googleapis.com/files/x"},
		{"no-op for base without path",
			"https://api.wandb.ai",
			"https://api.wandb.ai/files/e/p/r/f",
			"https://api.wandb.ai/files/e/p/r/f"},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			baseURL, err := url.Parse(tc.baseURL)
			require.NoError(t, err)
			request, err := http.NewRequest(http.MethodGet, tc.requestURL, http.NoBody)
			require.NoError(t, err)

			requests, err := httplayerstest.MapRequest(t,
				httplayers.PrefixPath(baseURL),
				request,
			)

			require.NoError(t, err)
			require.Len(t, requests, 1)
			assert.Equal(t, tc.expected, requests[0].URL.String())
		})
	}
}

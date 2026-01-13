package httplayers_test

import (
	"net/http"
	"net/url"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/httplayers"
)

type urlFilterTestHelper struct {
	ran bool
}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (h *urlFilterTestHelper) WrapHTTP(send httplayers.HTTPDoFunc) httplayers.HTTPDoFunc {
	return func(req *http.Request) (*http.Response, error) {
		h.ran = true
		return send(req)
	}
}

// noopHTTPDoFunc is an HTTPDoFunc for testing that just returns nil, nil.
func noopHTTPDoFunc(req *http.Request) (*http.Response, error) {
	return nil, nil
}

func TestURLFilter(t *testing.T) {
	testCases := []struct {
		name       string
		filterURL  string
		requestURL string
		matches    bool
	}{
		{"matches scheme, host, path",
			"https://api.wandb.ai/", "https://api.wandb.ai/graphql", true},

		{"no match if wrong scheme",
			"https://api.wandb.ai/", "http://api.wandb.ai/graphql", false},
		{"no match if wrong host",
			"https://api.wandb.ai/", "https://api.qa.wandb.ai/graphql", false},
		{"no match if wrong path",
			"https://proxy/wandb", "https://proxy/storage", false},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			filterURL, err := url.Parse(tc.filterURL)
			require.NoError(t, err)

			request, err := http.NewRequest(http.MethodGet, tc.requestURL, nil)
			require.NoError(t, err)

			matcher := &urlFilterTestHelper{}
			wrapper := httplayers.LimitTo(filterURL, matcher).WrapHTTP(noopHTTPDoFunc)
			_, _ = wrapper(request)

			assert.Equal(t, tc.matches, matcher.ran)
		})
	}
}

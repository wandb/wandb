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

			request, err := http.NewRequest(http.MethodGet, tc.requestURL, http.NoBody)
			require.NoError(t, err)

			filteredWrapper := httplayerstest.NewHTTPWrapperRecorder()
			requests, err := httplayerstest.MapRequest(t,
				httplayers.LimitTo(filterURL, filteredWrapper),
				request,
			)

			assert.NoError(t, err)
			assert.Equal(t, []*http.Request{request}, requests)

			if tc.matches {
				assert.Equal(t, []*http.Request{request}, filteredWrapper.Calls())
			} else {
				assert.Empty(t, filteredWrapper.Calls())
			}
		})
	}
}

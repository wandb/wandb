package filetransfer_test

import (
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/filetransfer"
)

func TestParseHeaders(t *testing.T) {
	t.Run("parses valid headers", func(t *testing.T) {
		headers, err := filetransfer.ParseHeaders([]string{
			"Content-Type: text/plain", // leading whitespace is trimmed
			"X-Empty:",                 // empty values are kept
			"X-Colon:a:b",              // only the first colon separates
		})

		assert.NoError(t, err)
		assert.Equal(t, http.Header{
			"Content-Type": {"text/plain"},
			"X-Empty":      {""},
			"X-Colon":      {"a:b"},
		}, headers)
	})

	t.Run("reports and skips entries without a colon", func(t *testing.T) {
		headers, err := filetransfer.ParseHeaders([]string{"Good:1", "no-colon", "also bad"})

		assert.Equal(t, http.Header{"Good": {"1"}}, headers)
		assert.ErrorContains(t, err, `["no-colon" "also bad"]`)
	})
}

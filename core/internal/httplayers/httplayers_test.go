package httplayers_test

import (
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/httplayers"
)

func TestConcat(t *testing.T) {
	var capturedRequest *http.Request
	captureRequest := func(req *http.Request) (*http.Response, error) {
		capturedRequest = req
		return nil, nil
	}
	request, err := http.NewRequest(
		http.MethodGet,
		"https://invalid",
		http.NoBody,
	)
	require.NoError(t, err)

	wrapper := httplayers.Concat(
		nil, // test that nils are safely ignored
		httplayers.DefaultHeaders(http.Header{
			http.CanonicalHeaderKey("x-test1"): []string{"inner1"},
			http.CanonicalHeaderKey("x-test2"): []string{"inner2"},
		}),
		nil,
		httplayers.DefaultHeaders(http.Header{
			http.CanonicalHeaderKey("x-test2"): []string{"outer2"},
			http.CanonicalHeaderKey("x-test3"): []string{"outer3"},
		}),
		nil,
	)
	_, _ = wrapper.WrapHTTP(captureRequest)(request)

	// The inner-most wrapper is applied last. For ExtraHeaders, incoming
	// headers take precedence, meaning the outer-most values are preserved.
	assert.Equal(t, []string{"inner1"}, capturedRequest.Header.Values("x-test1"))
	assert.Equal(t, []string{"outer2"}, capturedRequest.Header.Values("x-test2"))
	assert.Equal(t, []string{"outer3"}, capturedRequest.Header.Values("x-test3"))
}

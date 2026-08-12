package httplayers_test

import (
	"errors"
	"net/http"
	"net/url"
	"testing"

	"github.com/hashicorp/go-cleanhttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	. "github.com/wandb/wandb/core/internal/httplayers"
)

type errorHTTPWrapper struct {
	Err *url.Error
}

func (e errorHTTPWrapper) WrapHTTP(send HTTPDoFunc) HTTPDoFunc {
	return func(req *http.Request) (*http.Response, error) {
		return nil, e.Err
	}
}

func TestWrapRoundTripper_UnwrapsURLError(t *testing.T) {
	targetErr := errors.New("test error")
	wrapper := errorHTTPWrapper{&url.Error{
		Op:  http.MethodPost,
		URL: "https://invalid",
		Err: targetErr,
	}}
	client := cleanhttp.DefaultPooledClient()
	client.Transport = WrapRoundTripper(
		client.Transport,
		wrapper,
	)
	request, err := http.NewRequest(
		http.MethodPost,
		"https://invalid",
		http.NoBody,
	)
	require.NoError(t, err)

	_, err = client.Do(request)

	// Without unwrapping, the `Post "https://..."` part is doubled.
	assert.Equal(t,
		`Post "https://invalid": test error`,
		err.Error())
}

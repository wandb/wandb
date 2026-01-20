package httplayerstest

import (
	"bufio"
	"net/http"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/httplayers"
)

// MapRequest records the calls made by a wrapper to an inner HTTPDoFunc
// that always returns a successful response.
//
// Returns the requests made and any error returned by the wrapper.
func MapRequest(
	t *testing.T,
	wrapper httplayers.HTTPWrapper,
	req *http.Request,
) ([]*http.Request, error) {
	recorder := NewHTTPDoRecorder(t)
	_, err := wrapper.WrapHTTP(recorder.RecordHTTP)(req)
	return recorder.Calls(), err
}

// HTTPDoRecorder provides an HTTPDoFunc that records calls made to it.
type HTTPDoRecorder struct {
	t     *testing.T
	mu    sync.Mutex
	calls []*http.Request
}

// NewHTTPDoRecorder creates a new HTTPDoRecorder that returns a 200-status
// response and nil error on each call.
func NewHTTPDoRecorder(t *testing.T) *HTTPDoRecorder {
	return &HTTPDoRecorder{t: t}
}

// Calls returns the *http.Request values collected from calls to the recorder.
func (r *HTTPDoRecorder) Calls() []*http.Request {
	r.mu.Lock()
	defer r.mu.Unlock()
	return slices.Clone(r.calls)
}

// RecordHTTP records the request and returns a fake response.
func (r *HTTPDoRecorder) RecordHTTP(req *http.Request) (*http.Response, error) {
	// Close the body like a real Do function.
	if req.Body != nil {
		defer req.Body.Close()
	}

	r.mu.Lock()
	r.calls = append(r.calls, req)
	r.mu.Unlock()

	response, err := http.ReadResponse(
		bufio.NewReader(strings.NewReader("HTTP/1.1 200 OK\r\n\r\n")),
		req,
	)
	require.NoError(r.t, err)

	return response, nil
}

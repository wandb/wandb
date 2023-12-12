package clients

import (
	"bufio"
	"bytes"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
)

const (
	badPath  = "/bad/"
	goodPath = "/good/"
)

func TestClientResponseLogger(t *testing.T) {
	var buf bytes.Buffer
	bufWriter := bufio.NewWriter(&buf)
	slogger := slog.New(slog.NewTextHandler(bufWriter, nil))

	mux := http.NewServeMux()
	mux.HandleFunc(badPath, func(res http.ResponseWriter, req *http.Request) {
		res.WriteHeader(500)
		_, _ = res.Write([]byte("test_500_body"))
	})
	mux.HandleFunc(goodPath, func(res http.ResponseWriter, req *http.Request) {
		res.WriteHeader(200)
		_, _ = res.Write([]byte("happy"))
	})

	ts := httptest.NewServer(mux)
	defer ts.Close()

	client := NewRetryClient(
		WithRetryClientRetryMax(0),
		WithRetryClientResponseLogger(slogger, func(resp *http.Response) bool {
			return resp.StatusCode >= 400
		}),
	)
	client.Logger = slogger

	_, badErr := client.Get(ts.URL + badPath)
	assert.NotNil(t, badErr)
	_, goodErr := client.Get(ts.URL + goodPath)
	assert.Nil(t, goodErr)

	bufWriter.Flush()
	logBuffer := buf.String()
	assert.Contains(t, logBuffer, "test_500_body")
	assert.NotContains(t, logBuffer, "happy")
}

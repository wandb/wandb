package api_test

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/apitest"
)

func TestSend(t *testing.T) {
	server := NewRecordingServer()

	{
		defer server.Close()
		_, err := apitest.
			TestingClient(server.URL+"/wandb", api.ClientOptions{
				ExtraHeaders: map[string]string{
					"ClientHeader": "xyz",
				},
			}).
			Send(&api.Request{
				Method: http.MethodGet,
				Path:   "some/test/path",
				Body:   []byte("my test request"),
				Headers: map[string]string{
					"Header1": "one",
					"Header2": "two",
				},
			})
		assert.NoError(t, err)
	}

	allRequests := server.Requests()
	assert.Len(t, allRequests, 1)

	req := allRequests[0]
	assert.Equal(t, http.MethodGet, req.Method)
	assert.Equal(t, "/wandb/some/test/path", req.URL.Path)
	assert.Equal(t, "my test request", req.Body)
	assert.Equal(t, "one", req.Header.Get("Header1"))
	assert.Equal(t, "two", req.Header.Get("Header2"))
	assert.Equal(t, "xyz", req.Header.Get("ClientHeader"))
	assert.Equal(t, "wandb-core", req.Header.Get("User-Agent"))
	assert.Equal(t, "Basic YXBpOg==", req.Header.Get("Authorization"))
}

func TestDo_ToWandb_SetsAuth(t *testing.T) {
	server := NewRecordingServer()

	{
		defer server.Close()
		req, _ := http.NewRequest(
			http.MethodGet,
			server.URL+"/wandb/xyz",
			bytes.NewBufferString("test body"),
		)

		_, err := apitest.
			TestingClient(server.URL+"/wandb", api.ClientOptions{}).
			Do(req)

		assert.NoError(t, err)
	}

	assert.Len(t, server.Requests(), 1)
	assert.NotEmpty(t, server.Requests()[0].Header.Get("Authorization"))
}

func TestDo_NotToWandb_NoAuth(t *testing.T) {
	server := NewRecordingServer()

	{
		defer server.Close()
		req, _ := http.NewRequest(
			http.MethodGet,
			server.URL+"/notwandb/xyz",
			bytes.NewBufferString("test body"),
		)

		_, err := apitest.
			TestingClient(server.URL+"/wandb", api.ClientOptions{}).
			Do(req)

		assert.NoError(t, err)
	}

	assert.Len(t, server.Requests(), 1)
	assert.Empty(t, server.Requests()[0].Header.Get("Authorization"))
}

type RequestCopy struct {
	Method string
	URL    *url.URL
	Body   string
	Header http.Header
}

type RecordingServer struct {
	*httptest.Server

	requests *[]RequestCopy
	mu       *sync.Mutex
}

// All requests recorded by the server.
func (s *RecordingServer) Requests() []RequestCopy {
	s.mu.Lock()
	defer s.mu.Unlock()
	return *s.requests
}

// Returns a server that records all requests made to it.
func NewRecordingServer() *RecordingServer {
	requests := new([]RequestCopy)
	*requests = make([]RequestCopy, 0)

	mu := &sync.Mutex{}
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			body, _ := io.ReadAll(r.Body)

			mu.Lock()
			defer mu.Unlock()

			*requests = append(*requests,
				RequestCopy{
					Method: r.Method,
					URL:    r.URL,
					Body:   string(body),
					Header: r.Header,
				})

			w.Write([]byte("OK"))
		}),
	)

	return &RecordingServer{server, requests, mu}
}

package api_test

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"slices"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/pkg/observability"
)

func TestSend(t *testing.T) {
	server := NewRecordingServer()

	{
		defer server.Close()
		_, err := newClient(t, server.URL+"/wandb", api.ClientOptions{
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

		_, err := newClient(t, server.URL+"/wandb", api.ClientOptions{}).
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

		_, err := newClient(t, server.URL+"/wandb", api.ClientOptions{}).
			Do(req)

		assert.NoError(t, err)
	}

	assert.Len(t, server.Requests(), 1)
	assert.Empty(t, server.Requests()[0].Header.Get("Authorization"))
}

func newClient(
	t *testing.T,
	baseURLString string,
	opts api.ClientOptions,
) api.Client {
	baseURL, err := url.Parse(baseURLString)
	require.NoError(t, err)

	backend := api.New(api.BackendOptions{BaseURL: baseURL})
	return backend.NewClient(opts)
}

type RequestCopy struct {
	Method string
	URL    *url.URL
	Body   string
	Header http.Header
}

type RecordingServer struct {
	sync.Mutex
	*httptest.Server

	requests []RequestCopy
}

// All requests recorded by the server.
func (s *RecordingServer) Requests() []RequestCopy {
	s.Lock()
	defer s.Unlock()
	return slices.Clone(s.requests)
}

// Returns a server that records all requests made to it.
func NewRecordingServer() *RecordingServer {
	rs := &RecordingServer{
		requests: make([]RequestCopy, 0),
	}

	rs.Server = httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			body, _ := io.ReadAll(r.Body)

			rs.Lock()
			defer rs.Unlock()

			rs.requests = append(rs.requests,
				RequestCopy{
					Method: r.Method,
					URL:    r.URL,
					Body:   string(body),
					Header: r.Header,
				})

			_, _ = w.Write([]byte("OK"))
		}),
	)

	return rs
}

func TestNewClientWithProxy(t *testing.T) {
	proxyURL := ""
	testServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxyURL = r.Host // Capture the proxy URL
		if r.Host != proxyURL {
			t.Errorf("expected request to go through proxy, but got %s", r.URL.Host)
		}
	}))
	defer testServer.Close()

	proxyParsedURL, _ := url.Parse(testServer.URL)

	backend := api.New(api.BackendOptions{
		BaseURL: &url.URL{Scheme: "http", Host: "api.example.com"},
		Logger:  observability.NewNoOpLogger().Logger,
		APIKey:  "test_api_key",
	})

	clientOptions := api.ClientOptions{
		RetryMax:        5,
		RetryWaitMin:    1 * time.Second,
		RetryWaitMax:    5 * time.Second,
		NonRetryTimeout: api.DefaultNonRetryTimeout,
		ExtraHeaders: map[string]string{
			"Proxy-Authorization": "Basic dXNlcjpwYXNz",
		},
		Proxy: func(req *http.Request) (*url.URL, error) {
			return proxyParsedURL, nil
		},
	}

	client := backend.NewClient(clientOptions)

	// Create a test request
	testReq, err := http.NewRequest("GET", "http://api.example.com/test", nil)
	if err != nil {
		t.Fatalf("failed to create test request: %v", err)
	}

	resp, err := client.Do(testReq)
	if err != nil {
		t.Fatalf("failed to do test request: %v", err)
	}
	defer resp.Body.Close()

	// Check that Proxy-Authorization header is set
	proxyReqHeader := resp.Request.Header.Get("Proxy-Authorization")
	assert.Equal(t, "Basic dXNlcjpwYXNz", proxyReqHeader)
}

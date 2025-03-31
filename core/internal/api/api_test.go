package api_test

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/observability"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func TestSend(t *testing.T) {
	server := apitest.NewRecordingServer()
	settings := wbsettings.From(&spb.Settings{
		BaseUrl: &wrapperspb.StringValue{Value: server.URL + "/wandb"},
		ApiKey:  &wrapperspb.StringValue{Value: "test_api_key"},
	})

	{
		defer server.Close()
		_, err := newClient(t, settings, api.ClientOptions{
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
	assert.Equal(t, "my test request", string(req.Body))
	assert.Equal(t, "one", req.Header.Get("Header1"))
	assert.Equal(t, "two", req.Header.Get("Header2"))
	assert.Equal(t, "xyz", req.Header.Get("ClientHeader"))
	assert.Equal(t, "wandb-core", req.Header.Get("User-Agent"))
	assert.Equal(t, "Basic YXBpOnRlc3RfYXBpX2tleQ==",
		req.Header.Get("Authorization"))
}

func TestDo_ToWandb_SetsAuth(t *testing.T) {
	server := apitest.NewRecordingServer()
	settings := wbsettings.From(&spb.Settings{
		BaseUrl: &wrapperspb.StringValue{Value: server.URL + "/wandb"},
		ApiKey:  &wrapperspb.StringValue{Value: "test_api_key"},
	})

	{
		defer server.Close()
		req, _ := http.NewRequest(
			http.MethodGet,
			server.URL+"/wandb/xyz",
			bytes.NewBufferString("test body"),
		)

		_, err := newClient(t, settings, api.ClientOptions{}).
			Do(req)

		assert.NoError(t, err)
	}

	assert.Len(t, server.Requests(), 1)
	assert.NotEmpty(t, server.Requests()[0].Header.Get("Authorization"))
}

func TestDo_NotToWandb_NoAuth(t *testing.T) {
	server := apitest.NewRecordingServer()
	settings := wbsettings.From(&spb.Settings{
		BaseUrl: &wrapperspb.StringValue{Value: server.URL + "/wandb"},
		ApiKey:  &wrapperspb.StringValue{Value: "test_api_key"},
	})

	{
		defer server.Close()
		req, _ := http.NewRequest(
			http.MethodGet,
			server.URL+"/notwandb/xyz",
			bytes.NewBufferString("test body"),
		)

		_, err := newClient(t, settings, api.ClientOptions{}).
			Do(req)

		assert.NoError(t, err)
	}

	assert.Len(t, server.Requests(), 1)
	assert.Empty(t, server.Requests()[0].Header.Get("Authorization"))
}

func newClient(
	t *testing.T,
	settings *wbsettings.Settings,
	opts api.ClientOptions,
) api.Client {
	baseURL, err := url.Parse(settings.GetBaseURL())
	require.NoError(t, err)

	credentialProvider, err := api.NewCredentialProvider(
		settings,
		observability.NewNoOpLogger().Logger,
	)
	require.NoError(t, err)

	backend := api.New(api.BackendOptions{
		BaseURL:            baseURL,
		CredentialProvider: credentialProvider,
	})
	return backend.NewClient(opts)
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

	settings := wbsettings.From(&spb.Settings{
		ApiKey: &wrapperspb.StringValue{Value: "test_api_key"},
	})
	credentialProvider, err := api.NewCredentialProvider(settings, observability.NewNoOpLogger().Logger)
	require.NoError(t, err)

	backend := api.New(api.BackendOptions{
		BaseURL:            &url.URL{Scheme: "http", Host: "api.example.com"},
		Logger:             observability.NewNoOpLogger().Logger,
		CredentialProvider: credentialProvider,
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
	defer func() {
		_ = resp.Body.Close()
	}()

	// Check that Proxy-Authorization header is set
	proxyReqHeader := resp.Request.Header.Get("Proxy-Authorization")
	assert.Equal(t, "Basic dXNlcjpwYXNz", proxyReqHeader)
}

func TestNewClientWithRetry(t *testing.T) {
	serverCallCount := 0
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			serverCallCount++
			if serverCallCount == 1 {
				// induce a retry by returning a 500 error
				w.WriteHeader(http.StatusInternalServerError)
				_, _ = w.Write([]byte("Internal Server Error"))
				return
			}
			_, _ = w.Write([]byte("OK"))
		}),
	)

	serverURL := server.URL + "/wandb"
	settings := wbsettings.From(&spb.Settings{
		BaseUrl: &wrapperspb.StringValue{Value: serverURL},
		ApiKey:  &wrapperspb.StringValue{Value: "test_api_key"},
	})

	retryCallCount := 0
	client := newClient(t, settings, api.ClientOptions{
		RetryPolicy: func(ctx context.Context, resp *http.Response, err error) (bool, error) {
			if resp.StatusCode == http.StatusInternalServerError {
				return true, nil
			}
			return false, nil
		},
		RetryMax: 2,
		PrepareRetry: func(req *http.Request) error {
			retryCallCount++
			return nil
		},
	})

	// Create a test request
	testReq, err := http.NewRequest("GET", serverURL, nil)
	require.NoError(t, err)
	resp, err := client.Do(testReq)
	require.NoError(t, err)
	defer func() {
		_ = resp.Body.Close()
	}()

	assert.Equal(t, 1, retryCallCount)
	assert.Equal(t, 2, serverCallCount)
}

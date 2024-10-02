package server_test

import (
	"net/http"
	"os"
	"testing"

	"github.com/wandb/wandb/core/pkg/server"
)

func TestProxyFn(t *testing.T) {
	tests := []struct {
		name          string
		httpProxy     string
		httpsProxy    string
		requestURL    string
		envProxy      map[string]string
		expectedProxy string
		expectedError bool
	}{
		{
			name:          "Custom HTTP proxy",
			httpProxy:     "http://custom-proxy:8080",
			requestURL:    "http://example.com",
			expectedProxy: "http://custom-proxy:8080",
			expectedError: false,
		},
		{
			name:          "Custom HTTPS proxy",
			httpsProxy:    "http://custom-proxy:8443",
			requestURL:    "https://example.com",
			expectedProxy: "http://custom-proxy:8443",
			expectedError: false,
		},
		{
			name:          "No custom proxy, fallback to environment HTTP proxy",
			requestURL:    "http://example.com",
			envProxy:      map[string]string{"HTTP_PROXY": "http://env-proxy:8080"},
			expectedProxy: "http://env-proxy:8080",
			expectedError: false,
		},
		{
			name:          "Custom proxy with invalid URL",
			httpProxy:     "http:// invalid-url ",
			requestURL:    "http://example.com",
			expectedProxy: "",
			expectedError: true,
		},
		{
			name:          "Custom proxy overrides environment proxy",
			httpProxy:     "http://custom-proxy:8080",
			requestURL:    "http://example.com",
			envProxy:      map[string]string{"HTTP_PROXY": "http://env-proxy:8080"},
			expectedProxy: "http://custom-proxy:8080",
			expectedError: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Set environment variables for the test
			for env, value := range tt.envProxy {
				os.Setenv(env, value)
				defer os.Unsetenv(env)
			}

			req, err := http.NewRequest("GET", tt.requestURL, nil)
			if err != nil {
				t.Fatalf("http.NewRequest failed: %v", err)
			}

			proxyFn := server.ProxyFn(tt.httpProxy, tt.httpsProxy)
			proxyURL, err := proxyFn(req)

			if tt.expectedError {
				if err == nil {
					t.Errorf("expected an error but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("unexpected error: %v", err)
				return
			}

			if proxyURL == nil {
				if tt.expectedProxy != "" {
					t.Errorf("expected proxy URL %s but got nil", tt.expectedProxy)
				}
				return
			}

			if proxyURL.String() != tt.expectedProxy {
				t.Errorf("expected proxy URL %s but got %s", tt.expectedProxy, proxyURL.String())
			}
		})
	}
}

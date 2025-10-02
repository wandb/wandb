//go:build wireinject

package stream

import (
	"crypto/tls"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"
)

// ApiStreamID is a type alias for the stream ID used by ApiStream.
type ApiStreamID string

// InjectApiStream returns a new ApiStream as a Stream interface.
func InjectApiStream(
	streamID ApiStreamID,
	debugCorePath DebugCorePath,
	logLevel slog.Level,
	sentry *sentry_ext.Client,
	settings *settings.Settings,
) Streamer {
	wire.Build(apiStreamProviders)
	return nil
}

var apiStreamProviders = wire.NewSet(
	NewApiStream,
	wire.Bind(new(Streamer), new(*ApiStream)),
	wire.Bind(new(api.Peeker), new(*observability.Peeker)),
	wire.Struct(new(observability.Peeker)),
	NewBackend,
	NewGraphQLClient,
	provideApiStreamIDAsString,
	provideHttpClient,
	sharedmode.RandomClientID,
	streamLoggerProviders,
	RecordParserProviders,
)

// provideApiStreamIDAsString converts ApiStreamID to string for NewApiStream.
func provideApiStreamIDAsString(id ApiStreamID) string {
	return string(id)
}

// provideHttpClient creates an HTTP client configured with settings for
// timeout, proxy, SSL/TLS, and extra headers.
func provideHttpClient(settings *settings.Settings) *http.Client {
	// Create transport with proxy settings
	transport := &http.Transport{
		Proxy: ProxyFn(settings.GetHTTPProxy(), settings.GetHTTPSProxy()),
	}

	// Configure TLS settings if SSL verification should be disabled
	if settings.IsInsecureDisableSSL() {
		transport.TLSClientConfig = &tls.Config{
			InsecureSkipVerify: true,
		}
	}

	// Set proxy authorization header if present in extra headers
	extraHeaders := settings.GetExtraHTTPHeaders()
	if proxyAuth, ok := extraHeaders["Proxy-Authorization"]; ok {
		transport.ProxyConnectHeader = http.Header{
			"Proxy-Authorization": []string{proxyAuth},
		}
	}

	// Create client with configured transport and timeout
	// Using a general timeout that can be overridden by specific operation timeouts
	timeout := 30 * time.Second
	if graphqlTimeout := settings.GetGraphQLTimeout(); graphqlTimeout > 0 {
		timeout = graphqlTimeout
	}

	return &http.Client{
		Transport: transport,
		Timeout:   timeout,
	}
}

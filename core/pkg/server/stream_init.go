package server

// This file contains functions to construct the objects used by a Stream.

import (
	"fmt"
	"maps"
	"net/http"
	"net/url"
	"os"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
	"golang.org/x/time/rate"
)

// NewBackend returns a Backend or nil if we're offline.
func NewBackend(
	logger *observability.CoreLogger,
	settings *settings.Settings,
) *api.Backend {
	if settings.IsOffline() {
		return nil
	}

	baseURL, err := url.Parse(settings.GetBaseURL())
	if err != nil {
		logger.CaptureFatalAndPanic(
			fmt.Errorf("sender: failed to parse base URL: %v", err))
	}
	return api.New(api.BackendOptions{
		BaseURL: baseURL,
		Logger:  logger.Logger,
		APIKey:  settings.GetAPIKey(),
	})
}

// ProxyFn returns a function that returns a proxy URL for a given hhtp.Request.
//
// The function first checks if there's a custom proxy setting for the request
// URL scheme. If not, it falls back to the default environment proxy settings.
// If there is, it returns the custom proxy URL.
//
// This is useful if the user only want to proxy traffic to W&B, but not other traffic,
// as the standard environment proxy settings would potentially proxy all traffic.
//
// The custom proxy URLs are passed as arguments to the function.
//
// The default environment proxy settings are read from the environment variables
// HTTP_PROXY, HTTPS_PROXY, and NO_PROXY.
func ProxyFn(httpProxy string, httpsProxy string) func(req *http.Request) (*url.URL, error) {
	return func(req *http.Request) (*url.URL, error) {
		if req.URL.Scheme == "http" && httpProxy != "" {
			proxyURLParsed, err := url.Parse(httpProxy)
			if err != nil {
				return nil, err
			}
			return proxyURLParsed, nil
		} else if req.URL.Scheme == "https" && httpsProxy != "" {
			proxyURLParsed, err := url.Parse(httpsProxy)
			if err != nil {
				return nil, err
			}
			return proxyURLParsed, nil
		}

		// Fall back to the default environment proxy settings
		return http.ProxyFromEnvironment(req)
	}
}

func NewGraphQLClient(
	backend *api.Backend,
	settings *settings.Settings,
	peeker *observability.Peeker,
) graphql.Client {
	// TODO: This is used for the service account feature to associate the run
	// with the specified user. Note that we are using environment variables
	// here, instead of the settings object (which is ideally would be the only
	// setting used). We are doing this because, the default setting populates
	// the username with a value that not necessarily matches the username in
	// our app. There is also a precedence issue, where if the username is set
	// it will always be used, even if the email is set. Causing the owner of
	// to be wrong.
	// We should consider using the settings object here. But we need to make
	// sure that the username setting is populated correctly. Leaving this as is
	// for now just to avoid breakage in the service account feature.
	graphqlHeaders := map[string]string{
		"X-WANDB-USERNAME":   os.Getenv("WANDB_USERNAME"),
		"X-WANDB-USER-EMAIL": os.Getenv("WANDB_USER_EMAIL"),
	}
	maps.Copy(graphqlHeaders, settings.GetExtraHTTPHeaders())

	opts := api.ClientOptions{
		RetryPolicy:     clients.CheckRetry,
		RetryMax:        api.DefaultRetryMax,
		RetryWaitMin:    api.DefaultRetryWaitMin,
		RetryWaitMax:    api.DefaultRetryWaitMax,
		NonRetryTimeout: api.DefaultNonRetryTimeout,
		ExtraHeaders:    graphqlHeaders,
		NetworkPeeker:   peeker,
		Proxy:           ProxyFn(settings.GetHTTPProxy(), settings.GetHTTPSProxy()),
	}
	if retryMax := settings.GetGraphQLMaxRetries(); retryMax > 0 {
		opts.RetryMax = int(retryMax)
	}
	if retryWaitMin := settings.GetGraphQLRetryWaitMin(); retryWaitMin > 0 {
		opts.RetryWaitMin = retryWaitMin
	}
	if retryWaitMax := settings.GetGraphQLRetryWaitMax(); retryWaitMax > 0 {
		opts.RetryWaitMax = retryWaitMax
	}
	if timeout := settings.GetGraphQLTimeout(); timeout > 0 {
		opts.NonRetryTimeout = timeout
	}

	httpClient := backend.NewClient(opts)
	endpoint := fmt.Sprintf("%s/graphql", settings.GetBaseURL())

	return graphql.NewClient(endpoint, httpClient)
}

func NewFileStream(
	backend *api.Backend,
	logger *observability.CoreLogger,
	printer *observability.Printer,
	settings *settings.Settings,
	peeker api.Peeker,
) filestream.FileStream {
	fileStreamHeaders := map[string]string{}
	maps.Copy(fileStreamHeaders, settings.GetExtraHTTPHeaders())
	if settings.IsSharedMode() {
		fileStreamHeaders["X-WANDB-USE-ASYNC-FILESTREAM"] = "true"
	}

	opts := api.ClientOptions{
		RetryPolicy:     filestream.RetryPolicy,
		RetryMax:        filestream.DefaultRetryMax,
		RetryWaitMin:    filestream.DefaultRetryWaitMin,
		RetryWaitMax:    filestream.DefaultRetryWaitMax,
		NonRetryTimeout: filestream.DefaultNonRetryTimeout,
		ExtraHeaders:    fileStreamHeaders,
		NetworkPeeker:   peeker,
		Proxy:           ProxyFn(settings.GetHTTPProxy(), settings.GetHTTPSProxy()),
	}
	if retryMax := settings.GetFileStreamMaxRetries(); retryMax > 0 {
		opts.RetryMax = int(retryMax)
	}
	if retryWaitMin := settings.GetFileStreamRetryWaitMin(); retryWaitMin > 0 {
		opts.RetryWaitMin = retryWaitMin
	}
	if retryWaitMax := settings.GetFileStreamRetryWaitMax(); retryWaitMax > 0 {
		opts.RetryWaitMax = retryWaitMax
	}
	if timeout := settings.GetFileStreamTimeout(); timeout > 0 {
		opts.NonRetryTimeout = timeout
	}

	fileStreamRetryClient := backend.NewClient(opts)

	params := filestream.FileStreamParams{
		Settings:          settings,
		Logger:            logger,
		Printer:           printer,
		ApiClient:         fileStreamRetryClient,
		TransmitRateLimit: rate.NewLimiter(rate.Every(15*time.Second), 1),
	}

	return filestream.NewFileStream(params)
}

func NewFileTransferManager(
	fileTransferStats filetransfer.FileTransferStats,
	logger *observability.CoreLogger,
	settings *settings.Settings,
) filetransfer.FileTransferManager {
	fileTransferRetryClient := retryablehttp.NewClient()
	fileTransferRetryClient.Logger = logger
	fileTransferRetryClient.CheckRetry = filetransfer.FileTransferRetryPolicy
	fileTransferRetryClient.RetryMax = filetransfer.DefaultRetryMax
	fileTransferRetryClient.RetryWaitMin = filetransfer.DefaultRetryWaitMin
	fileTransferRetryClient.RetryWaitMax = filetransfer.DefaultRetryWaitMax
	fileTransferRetryClient.HTTPClient.Timeout = filetransfer.DefaultNonRetryTimeout
	fileTransferRetryClient.Backoff = clients.ExponentialBackoffWithJitter
	fileTransfers := filetransfer.NewFileTransfers(
		fileTransferRetryClient,
		logger,
		fileTransferStats,
	)

	// Set the Proxy function on the HTTP client.
	transport := &http.Transport{
		Proxy: ProxyFn(settings.GetHTTPProxy(), settings.GetHTTPSProxy()),
	}
	// Set the "Proxy-Authorization" header for the CONNECT requests
	// to the proxy server if the header is present in the extra headers.
	if header, ok := settings.GetExtraHTTPHeaders()["Proxy-Authorization"]; ok {
		transport.ProxyConnectHeader = http.Header{
			"Proxy-Authorization": []string{header},
		}
	}
	fileTransferRetryClient.HTTPClient.Transport = transport

	if retryMax := settings.GetFileTransferMaxRetries(); retryMax > 0 {
		fileTransferRetryClient.RetryMax = int(retryMax)
	}
	if retryWaitMin := settings.GetFileTransferRetryWaitMin(); retryWaitMin > 0 {
		fileTransferRetryClient.RetryWaitMin = retryWaitMin
	}
	if retryWaitMax := settings.GetFileTransferRetryWaitMax(); retryWaitMax > 0 {
		fileTransferRetryClient.RetryWaitMax = retryWaitMax
	}
	if timeout := settings.GetFileTransferTimeout(); timeout > 0 {
		fileTransferRetryClient.HTTPClient.Timeout = timeout
	}

	return filetransfer.NewFileTransferManager(
		filetransfer.WithLogger(logger),
		filetransfer.WithFileTransfers(fileTransfers),
		filetransfer.WithFileTransferStats(fileTransferStats),
	)
}

func NewRunfilesUploader(
	extraWork runwork.ExtraWork,
	logger *observability.CoreLogger,
	settings *settings.Settings,
	fileStream filestream.FileStream,
	fileTransfer filetransfer.FileTransferManager,
	fileWatcher watcher.Watcher,
	graphQL graphql.Client,
) runfiles.Uploader {
	return runfiles.NewUploader(runfiles.UploaderParams{
		ExtraWork:    extraWork,
		Logger:       logger,
		Settings:     settings,
		FileStream:   fileStream,
		FileTransfer: fileTransfer,
		GraphQL:      graphQL,
		FileWatcher:  fileWatcher,
		BatchDelay:   waiting.NewDelay(50 * time.Millisecond),
	})
}

package stream

// This file contains functions to construct the objects used by a Stream.

import (
	"fmt"
	"maps"
	"net/http"
	"net/url"

	"github.com/Khan/genqlient/graphql"
	"golang.org/x/time/rate"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"
)

// BaseURLFromSettings extracts the W&B server URL from W&B settings.
//
// It returns nil if offline.
func BaseURLFromSettings(
	logger *observability.CoreLogger,
	s *settings.Settings,
) api.WBBaseURL {
	if s.IsOffline() {
		return nil
	}

	baseURL, err := url.Parse(s.GetBaseURL())
	if err != nil {
		logger.CaptureFatalAndPanic(
			fmt.Errorf("stream_init: BaseURLFromSettings: %v", err))
	}

	return baseURL
}

// CredentialsFromSettings creates a CredentialProvider based on settings.
func CredentialsFromSettings(
	logger *observability.CoreLogger,
	s *settings.Settings,
) api.CredentialProvider {
	credentialProvider, err := api.NewCredentialProvider(s, logger.Logger)

	if err != nil {
		logger.CaptureFatalAndPanic(
			fmt.Errorf("stream_init: NewCredentialProvider: %v", err))
	}

	return credentialProvider
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
func ProxyFn(httpProxy, httpsProxy string) func(req *http.Request) (*url.URL, error) {
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
	baseURL api.WBBaseURL,
	clientID sharedmode.ClientID,
	credentialProvider api.CredentialProvider,
	logger *observability.CoreLogger,
	peeker *observability.Peeker,
	s *settings.Settings,
) graphql.Client {
	if s.IsOffline() {
		return nil
	}

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
		"X-WANDB-USERNAME":   s.GetUserName(),
		"X-WANDB-USER-EMAIL": s.GetEmail(),
	}
	maps.Copy(graphqlHeaders, s.GetExtraHTTPHeaders())
	// This header is used to indicate to the backend that the run is in shared
	// mode to prevent a race condition when two UpsertRun requests are made
	// simultaneously for the same run ID in shared mode.
	if s.IsSharedMode() {
		graphqlHeaders["X-WANDB-USE-ASYNC-FILESTREAM"] = "true"
		graphqlHeaders["X-WANDB-CLIENT-ID"] = string(clientID)
	}
	// When enabled, this header instructs the backend to compute the derived summary
	// using history updates, instead of relying on the SDK to calculate and send it.
	if s.IsEnableServerSideDerivedSummary() {
		graphqlHeaders["X-WANDB-SERVER-SIDE-DERIVED-SUMMARY"] = "true"
	}

	opts := api.ClientOptions{
		BaseURL:            baseURL,
		RetryPolicy:        clients.CheckRetry,
		RetryMax:           api.DefaultRetryMax,
		RetryWaitMin:       api.DefaultRetryWaitMin,
		RetryWaitMax:       api.DefaultRetryWaitMax,
		NonRetryTimeout:    api.DefaultNonRetryTimeout,
		ExtraHeaders:       graphqlHeaders,
		NetworkPeeker:      peeker,
		Proxy:              ProxyFn(s.GetHTTPProxy(), s.GetHTTPSProxy()),
		InsecureDisableSSL: s.IsInsecureDisableSSL(),
		CredentialProvider: credentialProvider,
		Logger:             logger.Logger,
	}
	if retryMax := s.GetGraphQLMaxRetries(); retryMax > 0 {
		opts.RetryMax = int(retryMax)
	}
	if retryWaitMin := s.GetGraphQLRetryWaitMin(); retryWaitMin > 0 {
		opts.RetryWaitMin = retryWaitMin
	}
	if retryWaitMax := s.GetGraphQLRetryWaitMax(); retryWaitMax > 0 {
		opts.RetryWaitMax = retryWaitMax
	}
	if timeout := s.GetGraphQLTimeout(); timeout > 0 {
		opts.NonRetryTimeout = timeout
	}

	httpClient := api.NewClient(opts)
	endpoint := fmt.Sprintf("%s/graphql", s.GetBaseURL())

	return graphql.NewClient(endpoint, api.AsStandardClient(httpClient))
}

func NewFileStream(
	factory *filestream.FileStreamFactory,
	baseURL api.WBBaseURL,
	clientID sharedmode.ClientID,
	credentialProvider api.CredentialProvider,
	logger *observability.CoreLogger,
	peeker api.Peeker,
	s *settings.Settings,
) filestream.FileStream {
	if s.IsOffline() {
		return nil
	}

	fileStreamHeaders := map[string]string{}
	maps.Copy(fileStreamHeaders, s.GetExtraHTTPHeaders())
	if s.IsSharedMode() {
		fileStreamHeaders["X-WANDB-USE-ASYNC-FILESTREAM"] = "true"
		fileStreamHeaders["X-WANDB-ASYNC-CLIENT-ID"] = string(clientID)
	}
	if s.IsEnableServerSideDerivedSummary() {
		fileStreamHeaders["X-WANDB-SERVER-SIDE-DERIVED-SUMMARY"] = "true"
	}

	opts := api.ClientOptions{
		BaseURL:            baseURL,
		RetryPolicy:        clients.RetryMostFailures,
		RetryMax:           filestream.DefaultRetryMax,
		RetryWaitMin:       filestream.DefaultRetryWaitMin,
		RetryWaitMax:       filestream.DefaultRetryWaitMax,
		NonRetryTimeout:    filestream.DefaultNonRetryTimeout,
		ExtraHeaders:       fileStreamHeaders,
		NetworkPeeker:      peeker,
		Proxy:              ProxyFn(s.GetHTTPProxy(), s.GetHTTPSProxy()),
		InsecureDisableSSL: s.IsInsecureDisableSSL(),
		CredentialProvider: credentialProvider,
		Logger:             logger.Logger,
	}
	if retryMax := s.GetFileStreamMaxRetries(); retryMax > 0 {
		opts.RetryMax = int(retryMax)
	}
	if retryWaitMin := s.GetFileStreamRetryWaitMin(); retryWaitMin > 0 {
		opts.RetryWaitMin = retryWaitMin
	}
	if retryWaitMax := s.GetFileStreamRetryWaitMax(); retryWaitMax > 0 {
		opts.RetryWaitMax = retryWaitMax
	}
	if timeout := s.GetFileStreamTimeout(); timeout > 0 {
		opts.NonRetryTimeout = timeout
	}

	fileStreamRetryClient := api.NewClient(opts)

	var transmitRateLimit *rate.Limiter
	if txInterval := s.GetFileStreamTransmitInterval(); txInterval > 0 {
		transmitRateLimit = rate.NewLimiter(rate.Every(txInterval), 1)
	}

	return factory.New(
		fileStreamRetryClient,
		/*heartbeatStopwatch=*/ nil,
		transmitRateLimit,
	)
}

func NewFileTransferManager(
	baseURL api.WBBaseURL,
	fileTransferStats filetransfer.FileTransferStats,
	logger *observability.CoreLogger,
	s *settings.Settings,
) filetransfer.FileTransferManager {
	if s.IsOffline() {
		return nil
	}

	httpOpts := api.ClientOptions{
		BaseURL:     baseURL,
		RetryPolicy: filetransfer.FileTransferRetryPolicy,
		Logger:      logger.Logger,

		RetryMax:        filetransfer.DefaultRetryMax,
		RetryWaitMin:    filetransfer.DefaultRetryWaitMin,
		RetryWaitMax:    filetransfer.DefaultRetryWaitMax,
		NonRetryTimeout: filetransfer.DefaultNonRetryTimeout,

		Proxy: ProxyFn(s.GetHTTPProxy(), s.GetHTTPSProxy()),

		InsecureDisableSSL: s.IsInsecureDisableSSL(),

		ExtraHeaders: s.GetExtraHTTPHeaders(),

		CredentialProvider: api.NoopCredentialProvider{},
	}

	if retryMax := s.GetFileTransferMaxRetries(); retryMax > 0 {
		httpOpts.RetryMax = int(retryMax)
	}
	if retryWaitMin := s.GetFileTransferRetryWaitMin(); retryWaitMin > 0 {
		httpOpts.RetryWaitMin = retryWaitMin
	}
	if retryWaitMax := s.GetFileTransferRetryWaitMax(); retryWaitMax > 0 {
		httpOpts.RetryWaitMax = retryWaitMax
	}
	if timeout := s.GetFileTransferTimeout(); timeout > 0 {
		httpOpts.NonRetryTimeout = timeout
	}

	httpClient := api.NewClient(httpOpts)

	fileTransfers := filetransfer.NewFileTransfers(
		httpClient,
		logger,
		fileTransferStats,
	)

	return filetransfer.NewFileTransferManager(
		filetransfer.FileTransferManagerOptions{
			Logger:            logger,
			FileTransfers:     fileTransfers,
			FileTransferStats: fileTransferStats,
		},
	)
}

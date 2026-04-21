package stream

// This file contains functions to construct the objects used by a Stream.

import (
	"fmt"
	"maps"
	"net/url"

	"github.com/Khan/genqlient/graphql"
	"golang.org/x/time/rate"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
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

// NewGraphQLClient creates a new GraphQL client.
//
// If the offline setting is true, it returns nil.
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

	extraHeaders := make(map[string]string)
	maps.Copy(extraHeaders, s.GetExtraHTTPHeaders())

	// This header is used to indicate to the backend that the run is in shared
	// mode to prevent a race condition when two UpsertRun requests are made
	// simultaneously for the same run ID in shared mode.
	if s.IsSharedMode() {
		extraHeaders["X-WANDB-USE-ASYNC-FILESTREAM"] = "true"
		extraHeaders["X-WANDB-CLIENT-ID"] = string(clientID)
	}
	// When enabled, this header instructs the backend to compute the derived summary
	// using history updates, instead of relying on the SDK to calculate and send it.
	if s.IsEnableServerSideDerivedSummary() {
		extraHeaders["X-WANDB-SERVER-SIDE-DERIVED-SUMMARY"] = "true"
	}

	return api.NewGQLClient(
		baseURL,
		clientID,
		credentialProvider,
		logger.Logger,
		peeker,
		s,
		extraHeaders,
	)
}

func NewFileStream(
	extraWork runwork.ExtraWork,
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
		BaseURL:         baseURL,
		RetryPolicy:     clients.RetryMostFailures,
		RetryMax:        filestream.DefaultRetryMax,
		RetryWaitMin:    filestream.DefaultRetryWaitMin,
		RetryWaitMax:    filestream.DefaultRetryWaitMax,
		NonRetryTimeout: filestream.DefaultNonRetryTimeout,
		ExtraHeaders:    fileStreamHeaders,
		NetworkPeeker:   peeker,
		Proxy: clients.ProxyFn(
			s.GetHTTPProxy(),
			s.GetHTTPSProxy(),
		),
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
		extraWork.BeforeEndCtx(),
		/*heartbeatPeriod=*/ 0, // use default
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

		Proxy: clients.ProxyFn(
			s.GetHTTPProxy(),
			s.GetHTTPSProxy(),
		),

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

package gql

import (
	"fmt"
	"maps"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"
)

func NewGQLClient(
	baseURL api.WBBaseURL,
	clientID sharedmode.ClientID,
	credentialProvider api.CredentialProvider,
	logger *observability.CoreLogger,
	peeker *observability.Peeker,
	s *settings.Settings,
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
		BaseURL:         baseURL,
		RetryPolicy:     clients.CheckRetry,
		RetryMax:        api.DefaultRetryMax,
		RetryWaitMin:    api.DefaultRetryWaitMin,
		RetryWaitMax:    api.DefaultRetryWaitMax,
		NonRetryTimeout: api.DefaultNonRetryTimeout,
		ExtraHeaders:    graphqlHeaders,
		NetworkPeeker:   peeker,
		Proxy: clients.ProxyFn(
			s.GetHTTPProxy(),
			s.GetHTTPSProxy(),
		),
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

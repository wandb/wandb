package api

import (
	"fmt"
	"log/slog"
	"maps"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"
)

func NewGQLClient(
	baseURL WBBaseURL,
	clientID sharedmode.ClientID,
	credentialProvider CredentialProvider,
	logger *slog.Logger,
	peeker Peeker,
	s *settings.Settings,
	extraHeaders map[string]string,
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
	maps.Copy(graphqlHeaders, extraHeaders)

	opts := ClientOptions{
		BaseURL:         baseURL,
		RetryPolicy:     clients.CheckRetry,
		RetryMax:        DefaultRetryMax,
		RetryWaitMin:    DefaultRetryWaitMin,
		RetryWaitMax:    DefaultRetryWaitMax,
		NonRetryTimeout: DefaultNonRetryTimeout,
		ExtraHeaders:    graphqlHeaders,
		NetworkPeeker:   peeker,
		Proxy: clients.ProxyFn(
			s.GetHTTPProxy(),
			s.GetHTTPSProxy(),
		),
		InsecureDisableSSL: s.IsInsecureDisableSSL(),
		CredentialProvider: credentialProvider,
		Logger:             logger,
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

	httpClient := NewClient(opts)
	endpoint := fmt.Sprintf("%s/graphql", s.GetBaseURL())

	return graphql.NewClient(endpoint, AsStandardClient(httpClient))
}

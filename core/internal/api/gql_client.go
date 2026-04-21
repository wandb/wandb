package api

import (
	"fmt"
	"log/slog"

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
	graphqlHeaders map[string]string,
) graphql.Client {

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

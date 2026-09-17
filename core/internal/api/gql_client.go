package api

import (
	"bytes"
	"fmt"
	"io"
	"log/slog"
	"maps"
	"net/http"

	"github.com/Khan/genqlient/graphql"
	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/httplayers"
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
	extraHeaders http.Header,
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
	graphqlHeaders := make(http.Header, len(extraHeaders)+2)
	graphqlHeaders.Set("X-WANDB-USERNAME", s.GetUserName())
	graphqlHeaders.Set("X-WANDB-USER-EMAIL", s.GetEmail())
	maps.Copy(graphqlHeaders, extraHeaders)

	opts := ClientOptions{
		RetryPolicy:        clients.CheckRetry,
		RetryMax:           DefaultRetryMax,
		RetryWaitMin:       DefaultRetryWaitMin,
		RetryWaitMax:       DefaultRetryWaitMax,
		NonRetryTimeout:    DefaultNonRetryTimeout,
		Proxy:              s.GetProxyFn(),
		ProxyConnectHeader: s.GetProxyConnectHeader(),
		InsecureDisableSSL: s.IsInsecureDisableSSL(),
		Logger:             logger,
		PreRetryLayers: httplayers.Concat(
			NetworkPeeker(peeker),
			httplayers.DefaultHeaders(graphqlHeaders),
			httplayers.LimitTo(baseURL, credentialProvider),
		),
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

	return graphql.NewClient(endpoint, &gqlHTTPClient{client: httpClient})
}

// gqlHTTPClient includes reading the response body in each retry attempt.
// Otherwise, genqlient reads it after the retry loop has finished, and a
// timeout or broken connection during that read fails the entire operation.
// Only GraphQL responses are buffered; other HTTP clients may stream files.
type gqlHTTPClient struct{ client RetryableClient }

func (c *gqlHTTPClient) Do(req *http.Request) (*http.Response, error) {
	retryingReq, err := retryablehttp.FromRequest(req)
	if err != nil {
		return nil, fmt.Errorf("api: GraphQL request: %w", err)
	}
	retryingReq.SetResponseHandler(bufferGQLResponse)
	return c.client.Do(retryingReq)
}

func bufferGQLResponse(resp *http.Response) error {
	// Preserve status-based handling of non-200 responses. In particular,
	// a body read failure must not cause a permanent HTTP error to be retried.
	if resp.StatusCode != http.StatusOK {
		return nil
	}

	body, err := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	resp.Body = http.NoBody
	if err != nil {
		return fmt.Errorf("api: reading GraphQL response body: %w", err)
	}

	// Leave JSON decoding and GraphQL errors to genqlient, so complete but
	// invalid responses do not become retryable transport errors.
	resp.Body = io.NopCloser(bytes.NewReader(body))
	return nil
}

package nfs

import (
	"fmt"
	"net/url"
	"os"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/api"
)

const defaultBaseURL = "https://api.wandb.ai"

// Config holds NFS CLI configuration.
type Config struct {
	APIKey  string
	BaseURL string
}

// LoadConfig reads configuration from environment variables.
func LoadConfig() (*Config, error) {
	apiKey := os.Getenv("WANDB_API_KEY")
	if apiKey == "" {
		return nil, fmt.Errorf("WANDB_API_KEY environment variable not set")
	}

	baseURL := os.Getenv("WANDB_BASE_URL")
	if baseURL == "" {
		baseURL = defaultBaseURL
	}

	return &Config{
		APIKey:  apiKey,
		BaseURL: baseURL,
	}, nil
}

// NewGraphQLClient creates a GraphQL client for NFS operations.
func NewGraphQLClient(cfg *Config) (graphql.Client, error) {
	baseURL, err := url.Parse(cfg.BaseURL)
	if err != nil {
		return nil, fmt.Errorf("invalid base URL: %w", err)
	}

	credProvider := api.NewAPIKeyCredentialProvider(cfg.APIKey)

	opts := api.ClientOptions{
		BaseURL:            baseURL,
		RetryMax:           api.DefaultRetryMax,
		RetryWaitMin:       api.DefaultRetryWaitMin,
		RetryWaitMax:       api.DefaultRetryWaitMax,
		NonRetryTimeout:    api.DefaultNonRetryTimeout,
		CredentialProvider: credProvider,
		ExtraHeaders:       map[string]string{},
	}

	httpClient := api.NewClient(opts)
	endpoint := fmt.Sprintf("%s/graphql", cfg.BaseURL)

	return graphql.NewClient(endpoint, api.AsStandardClient(httpClient)), nil
}

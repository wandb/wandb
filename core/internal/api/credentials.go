package api

import (
	"encoding/base64"
	"fmt"
	"net/http"

	"github.com/wandb/wandb/core/internal/settings"
)

// CredentialProvider adds credentials to HTTP requests.
type CredentialProvider interface {
	// Apply sets the appropriate authorization headers or parameters on the
	// HTTP request.
	Apply(req *http.Request) error
}

func NewCredentialProvider(
	settings *settings.Settings,
) (CredentialProvider, error) {
	if settings.GetIdentityTokenFile() != "" {
		return nil, fmt.Errorf("Identity federation via the wandb sdk " +
			"is temporarily unavailable in wandb-core, or version 0.18.0 or " +
			"later. Support for this feature will be reintroduced in an " +
			"upcoming release. To continue using this feature, please " +
			"downgrade to version 0.17.9 or lower using the following " +
			"command: pip install wandb==0.17.9. Thank you for your patience.")
	}
	return NewAPIKeyCredentialProvider(settings)
}

var _ CredentialProvider = &apiKeyCredentialProvider{}

type apiKeyCredentialProvider struct {
	apiKey string
}

func NewAPIKeyCredentialProvider(
	settings *settings.Settings,
) (CredentialProvider, error) {
	if err := settings.EnsureAPIKey(); err != nil {
		return nil, fmt.Errorf("couldn't get API key: %v", err)
	}

	return &apiKeyCredentialProvider{
		apiKey: settings.GetAPIKey(),
	}, nil
}

func (c *apiKeyCredentialProvider) Apply(req *http.Request) error {
	req.Header.Set(
		"Authorization",
		"Basic "+base64.StdEncoding.EncodeToString(
			[]byte("api:"+c.apiKey)),
	)
	return nil
}

package api

import (
	"encoding/base64"
	"fmt"
	"net/http"

	"github.com/wandb/wandb/core/internal/settings"
)

// CredentialProvider defines an interface for managing and applying credentialProvider.
type CredentialProvider interface {
	// Apply sets the appropriate authorization headers or parameters on the HTTP request.
	Apply(req *http.Request) error
}

func NewCredentialProvider(settings *settings.Settings) (CredentialProvider, error) {
	if settings.GetIdentityTokenFile() != "" {
		return nil, fmt.Errorf("Identity federation via the wandb sdk is temporarily unavailable in wandb-core, or version 0.18.0 " +
			"or later. Support for this feature will be reintroduced in an upcoming release. To continue using this " +
			"feature, please downgrade to version 0.17.9 or lower using the following command: pip install " +
			"wandb==0.17.9. Thank you for your patience.")
	}
	return NewAPIKeyCredentialProvider(settings)
}

var _ CredentialProvider = &APIKeyCredentialProvider{}

type APIKeyCredentialProvider struct {
	apiKey string
}

func NewAPIKeyCredentialProvider(settings *settings.Settings) (CredentialProvider, error) {
	if err := settings.EnsureAPIKey(); err != nil {
		return nil, err
	}

	return &APIKeyCredentialProvider{
		apiKey: settings.GetAPIKey(),
	}, nil
}

func (c *APIKeyCredentialProvider) Apply(req *http.Request) error {
	req.Header.Set(
		"Authorization",
		"Basic "+base64.StdEncoding.EncodeToString(
			[]byte("api:"+c.apiKey)),
	)
	return nil
}

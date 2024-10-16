package api_test

import (
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/api"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func TestNewAPIKeyCredentialProvider(t *testing.T) {
	settings := wbsettings.From(&spb.Settings{
		ApiKey: &wrapperspb.StringValue{Value: "test-api-key"},
	})
	credentialProvider, err := api.NewCredentialProvider(settings)
	require.NoError(t, err)

	req, err := http.NewRequest("GET", "http://example.com", nil)
	require.NoError(t, err)
	err = credentialProvider.Apply(req)
	require.NoError(t, err)

	assert.Equal(t, "Basic YXBpOnRlc3QtYXBpLWtleQ==", req.Header.Get("Authorization"))
}

func TestNewAPIKeyCredentialProvider_NoAPIKey(t *testing.T) {
	settings := wbsettings.From(&spb.Settings{})
	_, err := api.NewCredentialProvider(settings)
	assert.Error(t, err)
}

func TestNewAccessTokenCredentialProvider(t *testing.T) {
	settings := wbsettings.From(&spb.Settings{
		IdentityTokenFile: &wrapperspb.StringValue{Value: "jwt.txt"},
	})
	_, err := api.NewCredentialProvider(settings)
	assert.Error(t, err)
}

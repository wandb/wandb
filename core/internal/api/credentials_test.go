package api_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

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

func authServer() *httptest.Server {
	server := httptest.NewServer(nil)
	server.Config.Handler = http.HandlerFunc(
		func(w http.ResponseWriter, req *http.Request) {
			response := map[string]interface{}{
				"access_token": "fake-token",
				"expires_at":   time.Now().Add(time.Hour),
			}

			w.Header().Set("Content-Type", "application/json")

			if err := json.NewEncoder(w).Encode(response); err != nil {
				http.Error(w, "Failed to encode response", http.StatusInternalServerError)
				return
			}
		})
	return server
}

func TestNewOAuth2CredentialProvider_CreatesNewToken(t *testing.T) {
	// create identity token file
	tokenFile, err := os.CreateTemp("", "jwt.txt")
	require.NoError(t, err)
	defer os.Remove(tokenFile.Name())

	// write id token to file
	_, err = tokenFile.Write([]byte("id-token"))
	require.NoError(t, err)
	require.NoError(t, tokenFile.Close())

	// create credentials file
	credsFile, err := os.CreateTemp("", "credentials.json")
	require.NoError(t, err)
	defer os.Remove(credsFile.Name())
	//
	//// write credentials json to file
	_, err = credsFile.Write([]byte(`{"credentials": {}}`))
	require.NoError(t, err)
	require.NoError(t, credsFile.Close())

	server := authServer()
	defer server.Close()

	settings := wbsettings.From(&spb.Settings{
		BaseUrl:           &wrapperspb.StringValue{Value: server.URL},
		IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile.Name()},
		CredentialsFile:   &wrapperspb.StringValue{Value: credsFile.Name()},
	})
	credentialProvider, err := api.NewCredentialProvider(settings)
	require.NoError(t, err)

	req, err := http.NewRequest("GET", "http://example.com", nil)
	require.NoError(t, err)
	err = credentialProvider.Apply(req)
	require.NoError(t, err)

	assert.Equal(t, "Bearer fake-token", req.Header.Get("Authorization"))
}

func TestNewOAuth2CredentialProvider_RefreshesToken(t *testing.T) {

}

func TestNewOAuth2CredentialProvider_CreatesCredentialsFile(t *testing.T) {

}

func TestNewOAuth2CredentialProvider_CreatesNewTokenForNewBaseURL(t *testing.T) {

}

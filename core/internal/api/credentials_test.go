package api_test

import (
	"encoding/json"
	"net/http"
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/observability"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"golang.org/x/sync/errgroup"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func TestNewAPIKeyCredentialProvider(t *testing.T) {
	settings := wbsettings.From(&spb.Settings{
		ApiKey: &wrapperspb.StringValue{Value: "test-api-key"},
	})
	credentialProvider, err := api.NewCredentialProvider(settings, observability.NewNoOpLogger().Logger)
	require.NoError(t, err)

	req, err := http.NewRequest("GET", "http://example.com", nil)
	require.NoError(t, err)
	err = credentialProvider.Apply(req)
	require.NoError(t, err)

	assert.Equal(t, "Basic YXBpOnRlc3QtYXBpLWtleQ==", req.Header.Get("Authorization"))
}

func TestNewAPIKeyCredentialProvider_NoAPIKey(t *testing.T) {
	settings := wbsettings.From(&spb.Settings{})
	_, err := api.NewCredentialProvider(settings, observability.NewNoOpLogger().Logger)
	assert.Error(t, err)
}

func authServer(token string, expiresIn time.Duration) *apitest.RecordingServer {
	handler := func(w http.ResponseWriter, req *http.Request) {
		response := map[string]interface{}{
			"access_token": token,
			"expires_in":   expiresIn.Seconds(),
		}

		w.Header().Set("Content-Type", "application/json")

		if err := json.NewEncoder(w).Encode(response); err != nil {
			http.Error(w, "Failed to encode response", http.StatusInternalServerError)
			return
		}
	}
	server := apitest.NewRecordingServer(apitest.WithHandlerFunc(handler))
	return server
}

func TestNewOAuth2CredentialProvider(t *testing.T) {
	// create identity token file
	tokenFile, err := os.CreateTemp(t.TempDir(), "jwt.txt")
	require.NoError(t, err)
	defer func() {
		_ = os.Remove(tokenFile.Name())
	}()

	// write id token to file
	_, err = tokenFile.Write([]byte("id-token"))
	require.NoError(t, err)
	require.NoError(t, tokenFile.Close())

	credentialsFile := "credentials.json"
	defer func() {
		_ = os.Remove(credentialsFile)
	}()

	token := "fake-token"
	expiresIn := time.Hour
	server := authServer(token, expiresIn)
	defer server.Close()

	settings := wbsettings.From(&spb.Settings{
		// oauth2 provider should override api key setting
		ApiKey:            &wrapperspb.StringValue{Value: "test-api-key"},
		BaseUrl:           &wrapperspb.StringValue{Value: server.URL},
		IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile.Name()},
		CredentialsFile:   &wrapperspb.StringValue{Value: credentialsFile},
	})
	credentialProvider, err := api.NewCredentialProvider(settings, observability.NewNoOpLogger().Logger)
	require.NoError(t, err)

	req, err := http.NewRequest("GET", "http://example.com", nil)
	require.NoError(t, err)
	err = credentialProvider.Apply(req)
	require.NoError(t, err)

	assert.Equal(t, "Bearer "+token, req.Header.Get("Authorization"))

	// validate credentials file was written correctly
	file, err := os.ReadFile(credentialsFile)
	require.NoError(t, err)

	var data api.CredentialsFile
	err = json.Unmarshal(file, &data)
	require.NoError(t, err)

	assert.Equal(t, 1, len(data.Credentials))
	assert.Equal(t, token, data.Credentials[server.URL].AccessToken)
	assert.Equal(t, time.Now().UTC().Add(expiresIn).Round(time.Hour),
		time.Time(data.Credentials[server.URL].ExpiresAt).Round(time.Hour))
}

func TestNewOAuth2CredentialProvider_RefreshesToken(t *testing.T) {
	token := "fake-token"
	expiresIn := time.Hour
	server := authServer(token, expiresIn)
	defer server.Close()

	// create identity token file
	tokenFile, err := os.CreateTemp(t.TempDir(), "jwt.txt")
	require.NoError(t, err)
	defer func() {
		_ = os.Remove(tokenFile.Name())
	}()

	// write id token to file
	_, err = tokenFile.Write([]byte("id-token"))
	require.NoError(t, err)
	require.NoError(t, tokenFile.Close())

	// create credentials file
	credsFile, err := os.CreateTemp(t.TempDir(), "credentials.json")
	require.NoError(t, err)
	defer func() {
		_ = os.Remove(credsFile.Name())
	}()

	// if the token is going to expire in 3 minutes, it should be refreshed
	expiration := time.Now().UTC().Add(time.Minute * 3).Format("2006-01-02 15:04:05")
	// write expired access token to file
	_, err = credsFile.Write([]byte(`{
		"credentials":{
			"` + server.URL + `":{
				"access_token": "test",
				"expires_in": "` + expiration + `"
			}
		}
	}`))
	require.NoError(t, err)
	require.NoError(t, credsFile.Close())

	settings := wbsettings.From(&spb.Settings{
		BaseUrl:           &wrapperspb.StringValue{Value: server.URL},
		IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile.Name()},
		CredentialsFile:   &wrapperspb.StringValue{Value: credsFile.Name()},
	})
	credentialProvider, err := api.NewCredentialProvider(settings, observability.NewNoOpLogger().Logger)
	require.NoError(t, err)

	req, err := http.NewRequest("GET", "http://example.com", nil)
	require.NoError(t, err)
	err = credentialProvider.Apply(req)
	require.NoError(t, err)

	assert.Equal(t, "Bearer "+token, req.Header.Get("Authorization"))

	// validate credentials file was written correctly
	file, err := os.ReadFile(credsFile.Name())
	require.NoError(t, err)

	var data api.CredentialsFile
	err = json.Unmarshal(file, &data)
	require.NoError(t, err)

	assert.Equal(t, 1, len(data.Credentials))
	assert.Equal(t, token, data.Credentials[server.URL].AccessToken)
	assert.Equal(t, time.Now().UTC().Add(expiresIn).Round(time.Hour),
		time.Time(data.Credentials[server.URL].ExpiresAt).Round(time.Hour))
}

func TestNewOAuth2CredentialProvider_RefreshesTokenOnce(t *testing.T) {
	token := "fake-token"
	expiresIn := time.Hour
	server := authServer(token, expiresIn)
	defer server.Close()

	// create identity token file
	tokenFile, err := os.CreateTemp(t.TempDir(), "jwt.txt")
	require.NoError(t, err)
	defer func() {
		_ = os.Remove(tokenFile.Name())
	}()

	// write id token to file
	_, err = tokenFile.Write([]byte("id-token"))
	require.NoError(t, err)
	require.NoError(t, tokenFile.Close())

	// create credentials file
	credsFile, err := os.CreateTemp(t.TempDir(), "credentials.json")
	require.NoError(t, err)
	defer func() {
		_ = os.Remove(credsFile.Name())
	}()

	expiration := time.Now().UTC().Add(time.Minute * -3).Format("2006-01-02 15:04:05")
	// write expired access token to file
	_, err = credsFile.Write([]byte(`{
		"credentials": {
			"` + server.URL + `":{
				"access_token": "test",
				"expires_in": "` + expiration + `"
			}
		}
	}`))
	require.NoError(t, err)
	require.NoError(t, credsFile.Close())

	settings := wbsettings.From(&spb.Settings{
		BaseUrl:           &wrapperspb.StringValue{Value: server.URL},
		IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile.Name()},
		CredentialsFile:   &wrapperspb.StringValue{Value: credsFile.Name()},
	})
	credentialProvider, err := api.NewCredentialProvider(settings, observability.NewNoOpLogger().Logger)
	require.NoError(t, err)

	// issue 2 requests
	req, err := http.NewRequest("GET", "http://example.com", nil)
	require.NoError(t, err)
	req2, err := http.NewRequest("GET", "http://example.com", nil)
	require.NoError(t, err)

	var errGroup errgroup.Group
	errGroup.Go(func() error {
		return credentialProvider.Apply(req)
	})
	errGroup.Go(func() error {
		return credentialProvider.Apply(req2)
	})

	err = errGroup.Wait()
	require.NoError(t, err)

	assert.Equal(t, "Bearer fake-token", req.Header.Get("Authorization"))
	assert.Equal(t, "Bearer fake-token", req2.Header.Get("Authorization"))

	// auth server should only be called once
	assert.Equal(t, 1, len(server.Requests()))
}

func TestNewOAuth2CredentialProvider_CreatesNewTokenForNewBaseURL(t *testing.T) {
	// create identity token file
	tokenFile, err := os.CreateTemp(t.TempDir(), "jwt.txt")
	require.NoError(t, err)
	defer func() {
		_ = os.Remove(tokenFile.Name())
	}()

	// write id token to file
	_, err = tokenFile.Write([]byte("id-token"))
	require.NoError(t, err)
	require.NoError(t, tokenFile.Close())

	// create credentials file
	credsFile, err := os.CreateTemp(t.TempDir(), "credentials.json")
	require.NoError(t, err)
	defer func() {
		_ = os.Remove(credsFile.Name())
	}()

	// write credentials for other base url to credentials file
	_, err = credsFile.Write([]byte(`{
	   "credentials":{
		  "https://api.wandb.ai":{
			 "access_token":"test",
			 "expires_in":"2024-08-19 15:55:42"
		  }
	   }
	}`))
	require.NoError(t, err)
	require.NoError(t, credsFile.Close())

	token := "fake-token"
	expiresIn := time.Hour
	server := authServer(token, expiresIn)
	defer server.Close()

	settings := wbsettings.From(&spb.Settings{
		BaseUrl:           &wrapperspb.StringValue{Value: server.URL},
		IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile.Name()},
		CredentialsFile:   &wrapperspb.StringValue{Value: credsFile.Name()},
	})
	credentialProvider, err := api.NewCredentialProvider(settings, observability.NewNoOpLogger().Logger)
	require.NoError(t, err)

	req, err := http.NewRequest("GET", "http://example.com", nil)
	require.NoError(t, err)
	err = credentialProvider.Apply(req)
	require.NoError(t, err)

	assert.Equal(t, "Bearer fake-token", req.Header.Get("Authorization"))

	// credentials file should have 2 entries
	file, err := os.ReadFile(credsFile.Name())
	require.NoError(t, err)

	var data api.CredentialsFile
	err = json.Unmarshal(file, &data)
	require.NoError(t, err)

	var urls []string
	for k := range data.Credentials {
		urls = append(urls, k)
	}

	assert.ElementsMatch(t, []string{"https://api.wandb.ai", server.URL}, urls)
	assert.Equal(t, token, data.Credentials[server.URL].AccessToken)
	assert.Equal(t, time.Now().UTC().Add(expiresIn).Round(time.Hour),
		time.Time(data.Credentials[server.URL].ExpiresAt).Round(time.Hour))
}

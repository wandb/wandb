package api_test

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"golang.org/x/sync/errgroup"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/httplayerstest"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func exampleGetRequest(t *testing.T) *http.Request {
	req, err := http.NewRequest("GET", "http://example.com", http.NoBody)
	require.NoError(t, err)
	return req
}

func TestNewAPIKeyCredentialProvider(t *testing.T) {
	settings := wbsettings.From(&spb.Settings{
		ApiKey: &wrapperspb.StringValue{Value: "test-api-key"},
	})
	credentialProvider, err := api.NewCredentialProvider(
		settings,
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	reqs, err := httplayerstest.MapRequest(t,
		credentialProvider,
		exampleGetRequest(t),
	)

	require.NoError(t, err)
	require.Len(t, reqs, 1)
	assert.Equal(t,
		"Basic YXBpOnRlc3QtYXBpLWtleQ==",
		reqs[0].Header.Get("Authorization"))
}

func TestNewAPIKeyCredentialProvider_NoAPIKey(t *testing.T) {
	settings := wbsettings.From(&spb.Settings{})

	credentialProvider, err := api.NewCredentialProvider(
		settings,
		observabilitytest.NewTestLogger(t).Logger,
	)

	require.NoError(t, err)
	assert.Equal(t, credentialProvider, api.NoopCredentialProvider{})
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
	_, err = tokenFile.WriteString("id-token")
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
	credentialProvider, err := api.NewCredentialProvider(
		settings,
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	reqs, err := httplayerstest.MapRequest(t,
		credentialProvider,
		exampleGetRequest(t),
	)

	require.NoError(t, err)
	require.Len(t, reqs, 1)
	assert.Equal(t, "Bearer "+token, reqs[0].Header.Get("Authorization"))

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

func TestNewOAuth2CredentialProvider_TrimsTokenWhitespace(t *testing.T) {
	// Token files are often created with `echo` or an editor and end with
	// a newline, which must not become part of the token exchange request.
	tokenFile, err := os.CreateTemp(t.TempDir(), "jwt.txt")
	require.NoError(t, err)
	_, err = tokenFile.WriteString("id-token\n")
	require.NoError(t, err)
	require.NoError(t, tokenFile.Close())

	credentialsFile := filepath.Join(t.TempDir(), "credentials.json")

	server := authServer("fake-token", time.Hour)
	defer server.Close()

	settings := wbsettings.From(&spb.Settings{
		BaseUrl:           &wrapperspb.StringValue{Value: server.URL},
		IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile.Name()},
		CredentialsFile:   &wrapperspb.StringValue{Value: credentialsFile},
	})
	credentialProvider, err := api.NewCredentialProvider(
		settings,
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	_, err = httplayerstest.MapRequest(t,
		credentialProvider,
		exampleGetRequest(t),
	)
	require.NoError(t, err)

	exchanges := server.Requests()
	require.Len(t, exchanges, 1)
	assert.Equal(t,
		"grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=id-token",
		string(exchanges[0].Body))
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
	_, err = tokenFile.WriteString("id-token")
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
	_, err = credsFile.WriteString(`{
		"credentials":{
			"` + server.URL + `":{
				"access_token": "test",
				"expires_in": "` + expiration + `"
			}
		}
	}`)
	require.NoError(t, err)
	require.NoError(t, credsFile.Close())

	settings := wbsettings.From(&spb.Settings{
		BaseUrl:           &wrapperspb.StringValue{Value: server.URL},
		IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile.Name()},
		CredentialsFile:   &wrapperspb.StringValue{Value: credsFile.Name()},
	})
	credentialProvider, err := api.NewCredentialProvider(
		settings,
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	reqs, err := httplayerstest.MapRequest(t,
		credentialProvider,
		exampleGetRequest(t),
	)

	require.NoError(t, err)
	require.Len(t, reqs, 1)
	assert.Equal(t, "Bearer "+token, reqs[0].Header.Get("Authorization"))

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
	_, err = tokenFile.WriteString("id-token")
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
	_, err = credsFile.WriteString(`{
		"credentials": {
			"` + server.URL + `":{
				"access_token": "test",
				"expires_in": "` + expiration + `"
			}
		}
	}`)
	require.NoError(t, err)
	require.NoError(t, credsFile.Close())

	settings := wbsettings.From(&spb.Settings{
		BaseUrl:           &wrapperspb.StringValue{Value: server.URL},
		IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile.Name()},
		CredentialsFile:   &wrapperspb.StringValue{Value: credsFile.Name()},
	})
	credentialProvider, err := api.NewCredentialProvider(
		settings,
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	recorder := httplayerstest.NewHTTPDoRecorder(t)

	var errGroup errgroup.Group
	for range 2 {
		errGroup.Go(func() error {
			wrappedRecorder := credentialProvider.WrapHTTP(recorder.RecordHTTP)
			_, err := wrappedRecorder(exampleGetRequest(t))
			return err
		})
	}

	err = errGroup.Wait()
	require.NoError(t, err)

	calls := recorder.Calls()
	require.Len(t, calls, 2)
	assert.Equal(t, "Bearer fake-token", calls[0].Header.Get("Authorization"))
	assert.Equal(t, "Bearer fake-token", calls[1].Header.Get("Authorization"))

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
	_, err = tokenFile.WriteString("id-token")
	require.NoError(t, err)
	require.NoError(t, tokenFile.Close())

	// create credentials file
	credsFile, err := os.CreateTemp(t.TempDir(), "credentials.json")
	require.NoError(t, err)
	defer func() {
		_ = os.Remove(credsFile.Name())
	}()

	// write credentials for other base url to credentials file
	_, err = credsFile.WriteString(`{
	   "credentials":{
		  "https://api.wandb.ai":{
			 "access_token":"test",
			 "expires_in":"2024-08-19 15:55:42"
		  }
	   }
	}`)
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
	credentialProvider, err := api.NewCredentialProvider(
		settings,
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	reqs, err := httplayerstest.MapRequest(t,
		credentialProvider,
		exampleGetRequest(t),
	)

	require.NoError(t, err)
	require.Len(t, reqs, 1)
	assert.Equal(t, "Bearer "+token, reqs[0].Header.Get("Authorization"))

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

func TestOAuth2CredentialProvider_AccessToken(t *testing.T) {
	tokenFile := filepath.Join(t.TempDir(), "jwt.txt")
	require.NoError(t, os.WriteFile(tokenFile, []byte("id-token"), 0o600))
	credentialsFile := filepath.Join(t.TempDir(), "credentials.json")

	token := "fake-token"
	server := authServer(token, time.Hour)
	defer server.Close()

	settings := wbsettings.From(&spb.Settings{
		BaseUrl:           &wrapperspb.StringValue{Value: server.URL},
		IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile},
		CredentialsFile:   &wrapperspb.StringValue{Value: credentialsFile},
	})
	credentialProvider, err := api.NewCredentialProvider(
		settings,
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	tokenProvider, ok := credentialProvider.(api.AccessTokenProvider)
	require.True(t, ok, "the OAuth2 provider must expose access tokens")

	accessToken, err := tokenProvider.AccessToken()

	require.NoError(t, err)
	assert.Equal(t, token, accessToken)

	// The token is cached in the credentials file, like when it is used
	// for wandb-core's own requests.
	file, err := os.ReadFile(credentialsFile)
	require.NoError(t, err)
	var data api.CredentialsFile
	require.NoError(t, json.Unmarshal(file, &data))
	assert.Equal(t, token, data.Credentials[server.URL].AccessToken)
}

func TestNewOAuth2CredentialProvider_RereadsIdentityTokenFile(t *testing.T) {
	// Access tokens expiring within 5 minutes are refreshed on each use,
	// so every request below triggers a token exchange.
	server := authServer("fake-token", time.Minute)
	defer server.Close()

	tokenFile := filepath.Join(t.TempDir(), "jwt.txt")
	require.NoError(t, os.WriteFile(tokenFile, []byte("first-token"), 0o600))
	credentialsFile := filepath.Join(t.TempDir(), "credentials.json")

	settings := wbsettings.From(&spb.Settings{
		BaseUrl:           &wrapperspb.StringValue{Value: server.URL},
		IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile},
		CredentialsFile:   &wrapperspb.StringValue{Value: credentialsFile},
	})
	credentialProvider, err := api.NewCredentialProvider(
		settings,
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)

	_, err = httplayerstest.MapRequest(t, credentialProvider, exampleGetRequest(t))
	require.NoError(t, err)

	// An external process re-mints the short-lived identity token to the
	// same path, like during a run that outlives the token. The trailing
	// newline is typical of token files written by `echo` or an editor.
	require.NoError(t, os.WriteFile(tokenFile, []byte("second-token\n"), 0o600))

	_, err = httplayerstest.MapRequest(t, credentialProvider, exampleGetRequest(t))
	require.NoError(t, err)

	exchanges := server.Requests()
	require.Len(t, exchanges, 2)
	assert.Contains(t, string(exchanges[0].Body), "assertion=first-token")
	assert.Contains(t, string(exchanges[1].Body), "assertion=second-token")
}

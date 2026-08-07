package api_test

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"sync/atomic"
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
	"github.com/wandb/wandb/core/internal/wboperation"
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

func authHandler(token string, expiresIn time.Duration) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
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
}

func authServer(token string, expiresIn time.Duration) *apitest.RecordingServer {
	server := apitest.NewRecordingServer(
		apitest.WithHandlerFunc(authHandler(token, expiresIn)))
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

	accessToken, err := tokenProvider.AccessToken(t.Context())

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

// rejectingAuthServer is a token endpoint that always responds with the
// given status code and body.
func rejectingAuthServer(statusCode int, body string) *apitest.RecordingServer {
	handler := func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(statusCode)
		_, _ = w.Write([]byte(body))
	}
	return apitest.NewRecordingServer(apitest.WithHandlerFunc(handler))
}

// writeTokenFile writes an identity token file, returning its path and a
// path for the provider's credentials file.
func writeTokenFile(t *testing.T) (tokenFile, credentialsFile string) {
	tokenFile = filepath.Join(t.TempDir(), "jwt.txt")
	require.NoError(t, os.WriteFile(tokenFile, []byte("id-token"), 0o600))
	return tokenFile, filepath.Join(t.TempDir(), "credentials.json")
}

func oauth2ProviderForServer(
	t *testing.T,
	serverURL string,
) api.CredentialProvider {
	tokenFile, credentialsFile := writeTokenFile(t)

	settings := wbsettings.From(&spb.Settings{
		BaseUrl:           &wrapperspb.StringValue{Value: serverURL},
		IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile},
		CredentialsFile:   &wrapperspb.StringValue{Value: credentialsFile},
	})
	credentialProvider, err := api.NewCredentialProvider(
		settings,
		observabilitytest.NewTestLogger(t).Logger,
	)
	require.NoError(t, err)
	return credentialProvider
}

func TestOAuth2CredentialProvider_RejectedExchangeIsPermanent(t *testing.T) {
	server := rejectingAuthServer(
		http.StatusUnauthorized,
		`{"error":"invalid_grant"}`,
	)
	defer server.Close()
	credentialProvider := oauth2ProviderForServer(t, server.URL)

	_, err := httplayerstest.MapRequest(t,
		credentialProvider, exampleGetRequest(t))

	// A 4xx response means the same exchange can never succeed, so the
	// error must be marked permanent for retry policies to fail fast.
	var exchangeErr *api.TokenExchangeError
	require.ErrorAs(t, err, &exchangeErr)
	assert.Equal(t, http.StatusUnauthorized, exchangeErr.StatusCode)
	assert.True(t, exchangeErr.PermanentError())
	assert.Contains(t, err.Error(), "invalid_grant")
}

func TestOAuth2CredentialProvider_ExchangeServerErrorIsNotPermanent(t *testing.T) {
	server := rejectingAuthServer(http.StatusBadGateway, "upstream error")
	defer server.Close()
	credentialProvider := oauth2ProviderWithRetries(t, server.URL,
		api.TokenExchangeRetryMax, time.Minute)

	_, err := httplayerstest.MapRequest(t,
		credentialProvider, exampleGetRequest(t))

	// 5xx responses may be transient, so the error stays retryable.
	require.Error(t, err)
	var exchangeErr *api.TokenExchangeError
	assert.False(t, errors.As(err, &exchangeErr))
	assert.Contains(t, err.Error(), "upstream error")
}

// stalledAuthServer is a token endpoint that accepts requests but never
// answers them, like a server behind a silently dropped connection.
func stalledAuthServer(t *testing.T) *httptest.Server {
	release := make(chan struct{})

	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, req *http.Request) {
			select {
			case <-release:
			case <-req.Context().Done():
			}
		}))

	// The server must stop waiting for its handlers before it is closed.
	t.Cleanup(server.Close)
	t.Cleanup(func() { close(release) })

	return server
}

// oauth2ProviderWithRetries builds an OAuth2 credential provider whose
// exchange client uses the production retry policy with the retry count
// and per-attempt timeout the test needs, and with waits short enough for
// retries to be exercised quickly.
func oauth2ProviderWithRetries(
	t *testing.T,
	serverURL string,
	retryMax int,
	nonRetryTimeout time.Duration,
) api.CredentialProvider {
	baseURL, err := url.Parse(serverURL)
	require.NoError(t, err)
	logger := observabilitytest.NewTestLogger(t).Logger

	exchangeClient := api.NewClient(api.ClientOptions{
		BaseURL:            baseURL,
		RetryMax:           retryMax,
		RetryWaitMin:       time.Millisecond,
		RetryWaitMax:       10 * time.Millisecond,
		RetryPolicy:        api.TokenExchangeRetryPolicy,
		NonRetryTimeout:    nonRetryTimeout,
		CredentialProvider: api.NoopCredentialProvider{},
		Logger:             logger,
	})

	tokenFile, credentialsFile := writeTokenFile(t)
	credentialProvider, err := api.NewOAuth2CredentialProvider(
		serverURL,
		tokenFile,
		credentialsFile,
		exchangeClient,
		logger,
	)
	require.NoError(t, err)
	return credentialProvider
}

func TestOAuth2CredentialProvider_StalledExchangeFails(t *testing.T) {
	tests := []struct {
		name          string
		clientTimeout time.Duration
		ctxTimeout    time.Duration
	}{
		{
			name:          "client timeout",
			clientTimeout: 50 * time.Millisecond,
			ctxTimeout:    time.Minute,
		},
		{
			name:          "caller context deadline",
			clientTimeout: time.Minute,
			ctxTimeout:    50 * time.Millisecond,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server := stalledAuthServer(t)
			credentialProvider := oauth2ProviderWithRetries(
				t, server.URL, 0, test.clientTimeout)
			tokenProvider, ok := credentialProvider.(api.AccessTokenProvider)
			require.True(t, ok)

			ctx, cancel := context.WithTimeout(t.Context(), test.ctxTimeout)
			defer cancel()

			exchange := make(chan error, 1)
			go func() {
				_, err := tokenProvider.AccessToken(ctx)
				exchange <- err
			}()

			select {
			case err := <-exchange:
				// An unanswered exchange must not block the requests that
				// depend on the access token.
				assert.Error(t, err)
			case <-time.After(5 * time.Second):
				t.Fatal("the token exchange never returned")
			}
		})
	}
}

// sequencedAuthServer is a token endpoint that replies with the given
// statuses in order, repeating the last one.
func sequencedAuthServer(statuses ...int) *apitest.RecordingServer {
	var requests atomic.Int32
	handler := func(w http.ResponseWriter, req *http.Request) {
		status := statuses[min(int(requests.Add(1))-1, len(statuses)-1)]

		if status == http.StatusOK {
			authHandler("fake-token", time.Hour)(w, req)
			return
		}

		http.Error(w, "nope", status)
	}
	return apitest.NewRecordingServer(apitest.WithHandlerFunc(handler))
}

func TestOAuth2CredentialProvider_ExchangeRetries(t *testing.T) {
	tests := []struct {
		name          string
		statuses      []int
		wantRequests  int
		wantPermanent bool
	}{
		{
			name:          "a rejected identity token is not retried",
			statuses:      []int{http.StatusUnauthorized},
			wantRequests:  1,
			wantPermanent: true,
		},
		{
			name:          "a forbidden exchange is not retried",
			statuses:      []int{http.StatusForbidden},
			wantRequests:  1,
			wantPermanent: true,
		},
		{
			name:          "an unrecognized client error is not retried",
			statuses:      []int{http.StatusMethodNotAllowed},
			wantRequests:  1,
			wantPermanent: true,
		},
		{
			name:         "a server error is retried until it succeeds",
			statuses:     []int{http.StatusInternalServerError, http.StatusOK},
			wantRequests: 2,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server := sequencedAuthServer(test.statuses...)
			defer server.Close()
			credentialProvider := oauth2ProviderWithRetries(t, server.URL,
				api.TokenExchangeRetryMax, time.Minute)
			tokenProvider, ok := credentialProvider.(api.AccessTokenProvider)
			require.True(t, ok)

			token, err := tokenProvider.AccessToken(t.Context())

			assert.Len(t, server.Requests(), test.wantRequests)
			if !test.wantPermanent {
				require.NoError(t, err)
				assert.Equal(t, "fake-token", token)
				return
			}

			require.Error(t, err)
			var exchangeErr *api.TokenExchangeError
			require.ErrorAs(t, err, &exchangeErr)
			assert.True(t, exchangeErr.PermanentError())
		})
	}
}

func TestOAuth2CredentialProvider_CanceledContext(t *testing.T) {
	server := authServer("fake-token", time.Hour)
	defer server.Close()
	credentialProvider := oauth2ProviderForServer(t, server.URL)
	tokenProvider, ok := credentialProvider.(api.AccessTokenProvider)
	require.True(t, ok)

	ctx, cancel := context.WithCancel(t.Context())
	cancel()

	_, err := tokenProvider.AccessToken(ctx)

	// A caller whose context expired, like while waiting for another
	// caller's failed exchange, must not start an exchange of its own.
	require.ErrorIs(t, err, context.Canceled)
	assert.Empty(t, server.Requests())
}

func TestOAuth2CredentialProvider_ExchangeIsItsOwnSubtask(t *testing.T) {
	server := sequencedAuthServer(http.StatusInternalServerError, http.StatusOK)
	defer server.Close()
	credentialProvider := oauth2ProviderWithRetries(t, server.URL,
		api.TokenExchangeRetryMax, time.Minute)
	tokenProvider, ok := credentialProvider.(api.AccessTokenProvider)
	require.True(t, ok)

	ops := wboperation.NewOperations()
	op := ops.New("uploading data")
	op.MarkRetryingHTTPError(500, "500 Internal Server Error", "")

	_, err := tokenProvider.AccessToken(op.Context(t.Context()))

	// The exchange reports its retries on a subtask that is finished with
	// the exchange, leaving the status of the operation whose request
	// needed the token untouched.
	require.NoError(t, err)
	assert.Equal(t, "retrying HTTP 500 Internal Server Error", op.ErrorStatus())
	assert.Empty(t, ops.ToProto().Operations[0].Subtasks)
}

// tlsAuthServer is a token endpoint served over HTTPS with a self-signed
// certificate, like an on-prem deployment.
func tlsAuthServer(t *testing.T, token string) *httptest.Server {
	server := httptest.NewTLSServer(authHandler(token, time.Hour))
	t.Cleanup(server.Close)
	return server
}

func TestNewOAuth2CredentialProvider_InsecureDisableSSL(t *testing.T) {
	tests := []struct {
		name               string
		insecureDisableSSL bool
	}{
		{name: "certificate is verified by default"},
		{name: "verification is disabled by the setting", insecureDisableSSL: true},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server := tlsAuthServer(t, "fake-token")

			tokenFile, credentialsFile := writeTokenFile(t)
			settings := wbsettings.From(&spb.Settings{
				BaseUrl:           &wrapperspb.StringValue{Value: server.URL},
				IdentityTokenFile: &wrapperspb.StringValue{Value: tokenFile},
				CredentialsFile:   &wrapperspb.StringValue{Value: credentialsFile},
				InsecureDisableSsl: &wrapperspb.BoolValue{
					Value: test.insecureDisableSSL,
				},
			})
			credentialProvider, err := api.NewCredentialProvider(
				settings,
				observabilitytest.NewTestLogger(t).Logger,
			)
			require.NoError(t, err)

			reqs, err := httplayerstest.MapRequest(t,
				credentialProvider, exampleGetRequest(t))

			if !test.insecureDisableSSL {
				require.Error(t, err)
				assert.Contains(t, err.Error(), "certificate")
				return
			}
			require.NoError(t, err)
			require.Len(t, reqs, 1)
			assert.Equal(t,
				"Bearer fake-token", reqs[0].Header.Get("Authorization"))
		})
	}
}

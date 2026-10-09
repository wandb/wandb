package api

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/rogpeppe/go-internal/lockedfile"

	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/httplayers"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/wboperation"
)

const (
	// TokenExchangeRetryMax is the number of retries for one identity token
	// exchange.
	//
	// It is much smaller than DefaultRetryMax because the request that needs
	// the access token is itself retried, and because the exchange holds the
	// lock that every other request waits on.
	//
	// It is exported for tests, which build their own exchange clients.
	TokenExchangeRetryMax = 3

	// Waits between exchange attempts. These are shorter than the defaults
	// for the same reason the retry count is lower.
	tokenExchangeRetryWaitMin = time.Second
	tokenExchangeRetryWaitMax = 5 * time.Second

	// tokenExchangeAttemptTimeout bounds each exchange attempt.
	//
	// It is shorter than DefaultNonRetryTimeout so that the full retry
	// schedule fits within tokenExchangeTimeout.
	tokenExchangeAttemptTimeout = 10 * time.Second

	// tokenExchangeTimeout bounds one exchange including its retries when
	// the caller's context has no sooner deadline, like an access token
	// request from another process. Requests to the W&B server carry their
	// own per-attempt deadline, which bounds the exchange instead.
	tokenExchangeTimeout = 60 * time.Second

	// Refresh retries must finish within the server's grace period for a
	// resent refresh token, which is otherwise treated as a replay.
	refreshExchangeRetryMax       = 2
	refreshExchangeAttemptTimeout = 8 * time.Second
	refreshExchangeRetryWaitMin   = time.Second
	refreshExchangeRetryWaitMax   = 3 * time.Second
	refreshExchangeTimeout        = 30 * time.Second

	// CLIClientID is the CLI's public OAuth client ID. It is not a secret.
	CLIClientID = "wandb-cli"
)

// CredentialProvider adds credentials to HTTP requests.
type CredentialProvider httplayers.HTTPWrapper

// AccessTokenProvider is implemented by credential providers whose
// credentials take the form of an access token that other processes
// may need for authenticating with the W&B server directly.
type AccessTokenProvider interface {
	// AccessToken returns a valid access token, refreshing it if it is
	// at or near expiration.
	AccessToken(ctx context.Context) (string, error)
}

// NewCredentialProvider creates a new credential provider based on the SDK
// settings. Settings for JWT authentication are prioritized above API key
// authentication, and a browser login is used only when neither is configured.
func NewCredentialProvider(
	s *settings.Settings,
	logger *slog.Logger,
) (CredentialProvider, error) {
	if s.GetIdentityTokenFile() != "" {
		// The exchange must not use a credential provider: supplying its
		// credentials is what it is being used to make possible.
		exchangeClient := NewClient(ClientOptions{
			RetryMax:        TokenExchangeRetryMax,
			RetryWaitMin:    tokenExchangeRetryWaitMin,
			RetryWaitMax:    tokenExchangeRetryWaitMax,
			RetryPolicy:     TokenExchangeRetryPolicy,
			NonRetryTimeout: tokenExchangeAttemptTimeout,

			Proxy:              s.GetProxyFn(),
			ProxyConnectHeader: s.GetProxyConnectHeader(),

			InsecureDisableSSL: s.IsInsecureDisableSSL(),
			Logger:             logger,

			PreRetryLayers: httplayers.DefaultHeaders(s.GetExtraHTTPHeaders()),
		})

		return NewOAuth2CredentialProvider(
			s.GetBaseURL(),
			s.GetIdentityTokenFile(),
			s.GetCredentialsFile(),
			exchangeClient,
			logger,
		)
	}

	if apiKey := s.GetAPIKey(); apiKey != "" {
		return &apiKeyCredentialProvider{apiKey: apiKey}, nil
	}

	if hasStoredRefreshToken(s.GetCredentialsFile(), s.GetBaseURL()) {
		// Like the client above, this must not attach credentials of its own.
		exchangeClient := NewClient(ClientOptions{
			RetryMax:        refreshExchangeRetryMax,
			RetryWaitMin:    refreshExchangeRetryWaitMin,
			RetryWaitMax:    refreshExchangeRetryWaitMax,
			RetryPolicy:     TokenExchangeRetryPolicy,
			NonRetryTimeout: refreshExchangeAttemptTimeout,

			Proxy:              s.GetProxyFn(),
			ProxyConnectHeader: s.GetProxyConnectHeader(),

			InsecureDisableSSL: s.IsInsecureDisableSSL(),
			Logger:             logger,

			PreRetryLayers: httplayers.DefaultHeaders(s.GetExtraHTTPHeaders()),
		})

		return NewRefreshTokenCredentialProvider(
			s.GetBaseURL(),
			s.GetCredentialsFile(),
			exchangeClient,
			logger,
		), nil
	}

	return NoopCredentialProvider{}, nil
}

// NewAPIKeyCredentialProvider returns a credential provider that uses the given
// API key.
//
// This passes the API key in the Authorization header of the request using
// HTTP Basic Authentication. The API key is used as the password,
// while the username is left empty.
func NewAPIKeyCredentialProvider(apiKey string) CredentialProvider {
	return &apiKeyCredentialProvider{apiKey}
}

var _ CredentialProvider = &apiKeyCredentialProvider{}

type apiKeyCredentialProvider struct {
	// The W&B API key
	apiKey string
}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (c *apiKeyCredentialProvider) WrapHTTP(
	send httplayers.HTTPDoFunc,
) httplayers.HTTPDoFunc {
	return func(req *http.Request) (*http.Response, error) {
		_ = c.apply(req)
		return send(req)
	}
}

// apply sets the Authorization header on the request.
func (c *apiKeyCredentialProvider) apply(req *http.Request) error {
	req.Header.Set(
		"Authorization",
		"Basic "+base64.StdEncoding.EncodeToString(
			[]byte("api:"+c.apiKey)),
	)
	return nil
}

type NoopCredentialProvider struct{}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (c NoopCredentialProvider) WrapHTTP(
	send httplayers.HTTPDoFunc,
) httplayers.HTTPDoFunc {
	return send
}

// OAuth2CredentialProvider creates a credentials provider that exchanges a JWT
// for an access token via an authorization server. The access token is then used
// to authenticate API requests.
//
// The JWT is supplied via a file path that is passed in as an environment
// variable. When the OAuth2CredentialProvider is applied, it exchanges the JWT
// for an access token. It then attempts to save it to the credentials file along
// with its expiration. The expiration is checked each time the access token is
// used, and refreshed if it is at or near expiration.
//
// The exchange is made with httpClient, which bounds how long a request that
// depends on the access token can wait for it, and which must not itself
// supply credentials.
func NewOAuth2CredentialProvider(
	baseURL string,
	identityTokenFilePath string,
	credentialsFilePath string,
	httpClient RetryableClient,
	logger *slog.Logger,
) (CredentialProvider, error) {
	// Fail fast on misconfiguration. The token itself is re-read from the
	// file for each exchange: identity tokens are often short-lived and
	// re-minted to the same path, so the value read here may not stay valid
	// for the lifetime of the provider.
	if _, err := readIdentityToken(identityTokenFilePath); err != nil {
		return nil, err
	}
	return newOAuth2CredentialProvider(
		baseURL,
		credentialsFilePath,
		&assertionExchange{
			baseURL:               baseURL,
			identityTokenFilePath: identityTokenFilePath,
			httpClient:            httpClient,
		},
		logger,
	), nil
}

// NewRefreshTokenCredentialProvider creates a provider that renews access
// tokens using the refresh token a browser login stores in the credentials file.
func NewRefreshTokenCredentialProvider(
	baseURL string,
	credentialsFilePath string,
	httpClient RetryableClient,
	logger *slog.Logger,
) CredentialProvider {
	return newOAuth2CredentialProvider(
		baseURL,
		credentialsFilePath,
		&refreshTokenExchange{
			baseURL:    baseURL,
			httpClient: httpClient,
		},
		logger,
	)
}

func newOAuth2CredentialProvider(
	baseURL string,
	credentialsFilePath string,
	exchange tokenExchange,
	logger *slog.Logger,
) *oauth2CredentialProvider {
	return &oauth2CredentialProvider{
		baseURL:             baseURL,
		credentialsFilePath: credentialsFilePath,
		exchange:            exchange,
		// A separate file, since saving replaces the credentials file.
		fileMu:  lockedfile.MutexAt(credentialsFilePath + ".lock"),
		tokenMu: &sync.RWMutex{},
		logger:  logger,
	}
}

// tokenExchange obtains a new access token from the token endpoint.
type tokenExchange interface {
	// exchange returns a fresh access token. current holds the newest known
	// credentials for the base URL.
	exchange(ctx context.Context, current accessTokenInfo) (accessTokenInfo, error)

	// rotates reports whether the exchange invalidates the credential it used.
	rotates() bool
}

// assertionExchange trades an identity token for an access token using the JWT
// Bearer flow of RFC 7523.
type assertionExchange struct {
	baseURL               string
	identityTokenFilePath string
	httpClient            RetryableClient
}

func (e *assertionExchange) rotates() bool { return false }

func (e *assertionExchange) exchange(
	ctx context.Context,
	_ accessTokenInfo,
) (accessTokenInfo, error) {
	// Re-read each time. Identity tokens are re-minted to the same path.
	identityToken, err := readIdentityToken(e.identityTokenFilePath)
	if err != nil {
		return accessTokenInfo{}, err
	}

	ctx, cancel := context.WithTimeout(ctx, tokenExchangeTimeout)
	defer cancel()

	return postTokenRequest(ctx, e.httpClient, e.baseURL, url.Values{
		"grant_type": {"urn:ietf:params:oauth:grant-type:jwt-bearer"},
		"assertion":  {identityToken},
	})
}

// refreshTokenExchange trades a refresh token for a new access token, and for
// its own replacement, using the refresh grant of RFC 6749 section 6.
type refreshTokenExchange struct {
	baseURL    string
	httpClient RetryableClient
}

func (e *refreshTokenExchange) rotates() bool { return true }

func (e *refreshTokenExchange) exchange(
	ctx context.Context,
	current accessTokenInfo,
) (accessTokenInfo, error) {
	if current.RefreshToken == "" {
		return accessTokenInfo{}, &TokenExchangeError{
			StatusCode: http.StatusUnauthorized,
			Body:       "no refresh token stored; run `wandb login` again",
		}
	}

	ctx, cancel := context.WithTimeout(ctx, refreshExchangeTimeout)
	defer cancel()

	refreshed, err := postTokenRequest(ctx, e.httpClient, e.baseURL, url.Values{
		"grant_type":    {"refresh_token"},
		"refresh_token": {current.RefreshToken},
		"client_id":     {CLIClientID},
	})
	if err != nil {
		return accessTokenInfo{}, err
	}

	switch {
	case refreshed.AccessToken == "":
		return accessTokenInfo{}, errors.New(
			"api: refresh response did not include an access token")
	case !time.Now().Before(time.Time(refreshed.ExpiresAt)):
		// Otherwise every request would refresh again.
		return accessTokenInfo{}, errors.New(
			"api: refresh response did not include a positive expires_in")
	case refreshed.RefreshToken == "":
		// Otherwise the next refresh would resend a spent token.
		return accessTokenInfo{}, errors.New(
			"api: refresh response did not include a replacement refresh token")
	}

	return refreshed, nil
}

// postTokenRequest performs one token endpoint request and parses the response.
func postTokenRequest(
	ctx context.Context,
	httpClient RetryableClient,
	baseURL string,
	form url.Values,
) (accessTokenInfo, error) {
	// Own subtask: this exchange serves every request waiting on the token.
	op := wboperation.Get(ctx).Subtask("retrieving credentials")
	defer op.Finish()

	tokenURL := fmt.Sprintf("%s/oidc/token", baseURL)
	req, err := retryablehttp.NewRequestWithContext(
		op.Context(ctx), http.MethodPost, tokenURL, []byte(form.Encode()))
	if err != nil {
		return accessTokenInfo{}, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := httpClient.Do(req)
	if err != nil {
		return accessTokenInfo{}, err
	}
	defer func() {
		_ = resp.Body.Close()
	}()

	if resp.StatusCode != http.StatusOK {
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return accessTokenInfo{}, err
		}

		if isExchangeRejection(resp.StatusCode) {
			return accessTokenInfo{}, &TokenExchangeError{
				StatusCode: resp.StatusCode,
				Body:       string(body),
			}
		}

		return accessTokenInfo{}, fmt.Errorf(
			"failed to retrieve access token: HTTP %d: %s",
			resp.StatusCode, string(body))
	}

	var tokenResponse struct {
		AccessToken  string `json:"access_token"`
		RefreshToken string `json:"refresh_token"`
		ExpiresIn    int    `json:"expires_in"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&tokenResponse); err != nil {
		return accessTokenInfo{}, err
	}

	return accessTokenInfo{
		AccessToken:  tokenResponse.AccessToken,
		RefreshToken: tokenResponse.RefreshToken,
		ExpiresAt: ExpiresAt(
			time.Now().UTC().Add(time.Duration(tokenResponse.ExpiresIn) * time.Second)),
	}, nil
}

// hasStoredRefreshToken reports whether a browser login is stored for baseURL.
func hasStoredRefreshToken(credentialsFilePath string, baseURL string) bool {
	contents, err := os.ReadFile(credentialsFilePath)
	if err != nil {
		return false
	}

	var credsFile CredentialsFile
	if err := json.Unmarshal(contents, &credsFile); err != nil {
		return false
	}

	return credsFile.Credentials[baseURL].RefreshToken != ""
}

// TokenExchangeError is a definitive rejection of an identity token
// exchange by the server, like an invalid or expired identity token.
//
// Repeating the same exchange cannot succeed, so requests that depend on
// it must fail immediately instead of being retried. It implements the
// clients package's PermanentError interface without importing it.
type TokenExchangeError struct {
	// StatusCode is the HTTP status returned by the token endpoint.
	StatusCode int

	// Body is the token endpoint's response body, which typically
	// contains the OAuth error code and error_description.
	Body string
}

func (e *TokenExchangeError) Error() string {
	return fmt.Sprintf(
		"failed to retrieve access token: HTTP %d: %s",
		e.StatusCode, e.Body)
}

// PermanentError returns true: retrying the exchange cannot succeed.
func (e *TokenExchangeError) PermanentError() bool { return true }

// isExchangeRejection reports whether the token endpoint's status is a
// definitive rejection of the exchange, like an invalid or expired
// identity token, unknown user or bad audience. 429 and 5xx responses
// may be transient, so they are not rejections.
func isExchangeRejection(statusCode int) bool {
	return statusCode >= 400 && statusCode < 500 &&
		statusCode != http.StatusTooManyRequests
}

// TokenExchangeRetryPolicy retries the same failures as RetryMostFailures,
// except that no definitive rejection of the exchange is retried.
//
// RetryMostFailures retries 4xx statuses it does not recognize; for the
// token exchange, that would discard the server's response and hide the
// rejection from the requests waiting on the exchange.
//
// It is exported for tests, which build their own exchange clients.
func TokenExchangeRetryPolicy(
	ctx context.Context,
	resp *http.Response,
	err error,
) (bool, error) {
	if resp != nil && isExchangeRejection(resp.StatusCode) {
		return false, nil
	}

	return clients.RetryMostFailures(ctx, resp, err)
}

// readIdentityToken reads the identity token (a JWT) from the file.
func readIdentityToken(path string) (string, error) {
	identityToken, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("api: failed to read identity token file: %v", err)
	}

	// Strip surrounding whitespace, like the trailing newline written
	// by `echo` and most editors, which would otherwise be sent as
	// part of the token.
	return strings.TrimSpace(string(identityToken)), nil
}

type oauth2CredentialProvider struct {
	// The URL of the W&B API.
	baseURL string

	// The access token and its metadata.
	tokenInfo accessTokenInfo

	// The file path to the access token and its metadata.
	credentialsFilePath string

	exchange tokenExchange

	// Serializes exchanges across processes sharing the credentials file.
	fileMu *lockedfile.Mutex

	tokenMu *sync.RWMutex

	logger *slog.Logger
}

// ExpiresAt is a custom type representing a time.Time value. It is used to handle
// expiration times in a specific string format when serializing/deserializing JSON data.
type ExpiresAt time.Time

const expiresAtLayout = "2006-01-02 15:04:05"

func (e *ExpiresAt) UnmarshalJSON(data []byte) error {
	var timeString string
	if err := json.Unmarshal(data, &timeString); err != nil {
		return err
	}

	parsedTime, err := time.Parse(expiresAtLayout, timeString)
	if err != nil {
		return err
	}

	*e = ExpiresAt(parsedTime)
	return nil
}

func (e ExpiresAt) MarshalJSON() ([]byte, error) {
	formattedTime := time.Time(e).Format(expiresAtLayout)
	return json.Marshal(formattedTime)
}

type accessTokenInfo struct {
	// The time at which the access token will expire.
	ExpiresAt ExpiresAt `json:"expires_at"`

	// The access token to use for authentication.
	AccessToken string `json:"access_token"`

	// The refresh token from a browser login, if any.
	RefreshToken string `json:"refresh_token,omitempty"`
}

func (c *accessTokenInfo) IsTokenExpiring() bool {
	return time.Until(time.Time(c.ExpiresAt)) <= time.Minute*5
}

// CredentialsFile is used when serializing/deserializing JSON data from the
// credentials file.
type CredentialsFile struct {
	Credentials map[string]accessTokenInfo `json:"credentials"`
}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (c *oauth2CredentialProvider) WrapHTTP(
	send httplayers.HTTPDoFunc,
) httplayers.HTTPDoFunc {
	return func(req *http.Request) (*http.Response, error) {
		err := c.apply(req)
		if err != nil {
			return nil, httplayers.URLError(req, err)
		}

		return send(req)
	}
}

// apply fetches a new access token if necessary and supplies it to the request
// via the Authorization header as a Bearer token.
func (c *oauth2CredentialProvider) apply(req *http.Request) error {
	token, err := c.AccessToken(req.Context())
	if err != nil {
		return err
	}

	req.Header.Set("Authorization", "Bearer "+token)
	return nil
}

var _ AccessTokenProvider = &oauth2CredentialProvider{}

// AccessToken implements AccessTokenProvider.AccessToken.
func (c *oauth2CredentialProvider) AccessToken(
	ctx context.Context,
) (string, error) {
	if c.shouldRefreshToken() {
		err := c.loadCredentials(ctx)
		if err != nil {
			return "", err
		}
	}

	c.tokenMu.RLock()
	defer c.tokenMu.RUnlock()
	return c.tokenInfo.AccessToken, nil
}

func (c *oauth2CredentialProvider) shouldRefreshToken() bool {
	c.tokenMu.RLock()
	defer c.tokenMu.RUnlock()

	return c.tokenInfo.IsTokenExpiring()
}

// Ensures the access token is valid by refreshing it if
// necessary, using a mutex to prevent concurrent refreshes. It first checks for
// a non-expiring token in memory or the credentials file. If none is found, it
// fetches a new token and saves it.
func (c *oauth2CredentialProvider) loadCredentials(ctx context.Context) error {
	c.tokenMu.Lock()
	defer c.tokenMu.Unlock()

	if !c.tokenInfo.IsTokenExpiring() {
		return nil
	}

	// The lock wait ignores the context, so the deadline may already have passed.
	if err := ctx.Err(); err != nil {
		return err
	}

	// Concurrent refreshes of a rotating token retire each other's tokens.
	// Locking is best effort; the server tolerates a brief overlap.
	if unlock, err := c.fileMu.Lock(); err != nil {
		c.logger.Warn("failed to lock credentials file; refreshing anyway",
			"file path", c.credentialsFilePath,
			"error", err,
		)
	} else {
		defer unlock()
	}

	// The previous lock holder may have already refreshed.
	credsFile, _ := c.tryLoadCredentialsFromFile()
	stored := credsFile.Credentials[c.baseURL]
	if !stored.IsTokenExpiring() {
		c.tokenInfo = stored
		return nil
	}

	// After a failed save, the file holds an already-spent refresh token.
	current := stored
	if time.Time(c.tokenInfo.ExpiresAt).After(time.Time(stored.ExpiresAt)) {
		current = c.tokenInfo
	}

	token, err := c.exchange.exchange(ctx, current)
	if err != nil {
		return fmt.Errorf("api: couldn't fetch access token: %w", err)
	}

	if err := c.saveCredentialsToFile(credsFile, token); err != nil {
		if c.exchange.rotates() {
			c.logger.Error(
				"api: couldn't save refreshed credentials; "+
					"the stored login will not work after this process exits",
				"error", err.Error())
		} else {
			c.logger.Warn("failed to update credentials file", "error", err.Error())
		}
	}

	c.tokenInfo = token
	return nil
}

// Attempts to load the access token from the credentials file.
func (c *oauth2CredentialProvider) tryLoadCredentialsFromFile() (CredentialsFile, bool) {
	var credsFile CredentialsFile

	file, err := os.ReadFile(c.credentialsFilePath)
	if err != nil {
		c.logger.Warn("failed to read credentials file",
			"file path", c.credentialsFilePath,
			"error", err,
		)
		return credsFile, false
	}

	if err := json.Unmarshal(file, &credsFile); err != nil {
		c.logger.Warn("failed to read credentials file", "error", err.Error())
		return credsFile, false
	}

	if credsFile.Credentials == nil {
		credsFile.Credentials = make(map[string]accessTokenInfo)
	}

	return credsFile, true
}

// saveCredentialsToFile stores token for this provider's base URL.
//
// The file is replaced atomically so a partial write cannot lose a refresh token.
func (c *oauth2CredentialProvider) saveCredentialsToFile(
	credentials CredentialsFile,
	token accessTokenInfo,
) error {
	if credentials.Credentials == nil {
		credentials.Credentials = make(map[string]accessTokenInfo)
	}
	credentials.Credentials[c.baseURL] = token

	contents, err := json.MarshalIndent(credentials, "", "  ")
	if err != nil {
		return err
	}

	dir := filepath.Dir(c.credentialsFilePath)
	temp, err := os.CreateTemp(dir, ".credentials-*.json")
	if err != nil {
		return err
	}
	tempPath := temp.Name()
	defer func() {
		_ = os.Remove(tempPath)
	}()

	if err := temp.Chmod(0o600); err != nil {
		_ = temp.Close()
		return err
	}
	if _, err := temp.Write(contents); err != nil {
		_ = temp.Close()
		return err
	}
	// Flush before rename so a crash cannot leave an empty credentials file.
	if err := temp.Sync(); err != nil {
		_ = temp.Close()
		return err
	}
	if err := temp.Close(); err != nil {
		return err
	}

	return os.Rename(tempPath, c.credentialsFilePath)
}

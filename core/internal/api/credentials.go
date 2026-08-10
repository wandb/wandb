package api

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/hashicorp/go-retryablehttp"

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
// authentication.
func NewCredentialProvider(
	s *settings.Settings,
	logger *slog.Logger,
) (CredentialProvider, error) {
	if s.GetIdentityTokenFile() != "" {
		baseURL, err := url.Parse(s.GetBaseURL())
		if err != nil {
			return nil, fmt.Errorf("api: invalid base URL: %v", err)
		}

		// The exchange must not use a credential provider: supplying its
		// credentials is what it is being used to make possible.
		exchangeClient := NewClient(ClientOptions{
			BaseURL:            baseURL,
			RetryMax:           TokenExchangeRetryMax,
			RetryWaitMin:       tokenExchangeRetryWaitMin,
			RetryWaitMax:       tokenExchangeRetryWaitMax,
			RetryPolicy:        TokenExchangeRetryPolicy,
			NonRetryTimeout:    tokenExchangeAttemptTimeout,
			ExtraHeaders:       s.GetExtraHTTPHeaders(),
			Proxy:              clients.ProxyFn(s.GetHTTPProxy(), s.GetHTTPSProxy()),
			InsecureDisableSSL: s.IsInsecureDisableSSL(),
			CredentialProvider: NoopCredentialProvider{},
			Logger:             logger,
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
	return &oauth2CredentialProvider{
		baseURL:               baseURL,
		identityTokenFilePath: identityTokenFilePath,
		credentialsFilePath:   credentialsFilePath,
		httpClient:            httpClient,
		tokenMu:               &sync.RWMutex{},
		logger:                logger,
	}, nil
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

	// The path of the file supplying the identity token.
	identityTokenFilePath string

	// The access token and its metadata.
	tokenInfo accessTokenInfo

	// The file path to the access token and its metadata.
	credentialsFilePath string

	// The client used to exchange the identity token for an access token.
	httpClient RetryableClient

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

	// if the access token has already been refreshed, return early
	if !c.tokenInfo.IsTokenExpiring() {
		return nil
	}

	// The wait for the lock is not bounded by the context, whose deadline
	// may have passed, like when the previous holder spent it on a failed
	// exchange. Don't start an exchange that cannot succeed.
	if err := ctx.Err(); err != nil {
		return err
	}

	credsFile, ok := c.tryLoadCredentialsFromFile()
	if ok {
		accessToken, ok := credsFile.Credentials[c.baseURL]
		if ok && !accessToken.IsTokenExpiring() {
			c.tokenInfo = accessToken
			return nil
		}
	}

	token, err := c.fetchAccessToken(ctx)
	if err != nil {
		return fmt.Errorf("api: couldn't fetch access token: %w", err)
	}
	c.tokenInfo = token

	c.trySaveCredentialsToFile(credsFile)

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

// Attempts to save the access token to the credentials file.
func (c *oauth2CredentialProvider) trySaveCredentialsToFile(credentials CredentialsFile) {
	if credentials.Credentials == nil {
		credentials.Credentials = make(map[string]accessTokenInfo)
	}
	credentials.Credentials[c.baseURL] = c.tokenInfo

	file, err := json.MarshalIndent(credentials, "", "  ")
	if err != nil {
		c.logger.Warn("failed to update credentials file", "error", err.Error())
		return
	}
	err = os.WriteFile(c.credentialsFilePath, file, 0o600)
	if err != nil {
		c.logger.Warn("failed to write credentials file", "error", err.Error())
	}
}

// Reads the identity token from a file and exchanges it for
// an access token from the authorization server using the JWT Bearer flow defined
// in OAuth RFC 7523. The access token is then returned with its expiration time.
func (c *oauth2CredentialProvider) fetchAccessToken(
	ctx context.Context,
) (accessTokenInfo, error) {
	// Read the file for each exchange: short-lived identity tokens are
	// re-minted to the same path, and an exchange must use the current
	// file contents rather than the token present at startup.
	identityToken, err := readIdentityToken(c.identityTokenFilePath)
	if err != nil {
		return accessTokenInfo{}, err
	}

	// The exchange reports its retries on its own subtask, not as the
	// outer request's status: it serves every request waiting on the
	// token, not just the one whose context this is.
	op := wboperation.Get(ctx).Subtask("retrieving credentials")
	defer op.Finish()

	ctx, cancel := context.WithTimeout(op.Context(ctx), tokenExchangeTimeout)
	defer cancel()

	tokenURL := fmt.Sprintf("%s/oidc/token", c.baseURL)
	data := fmt.Sprintf(
		"grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=%s",
		url.QueryEscape(identityToken),
	)
	req, err := retryablehttp.NewRequestWithContext(
		ctx, http.MethodPost, tokenURL, []byte(data))
	if err != nil {
		return accessTokenInfo{}, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := c.httpClient.Do(req)
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

		// Repeating a rejected exchange cannot succeed, so the requests
		// that depend on it must fail immediately instead of retrying.
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
		AccessToken string `json:"access_token"`
		ExpiresIn   int    `json:"expires_in"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&tokenResponse); err != nil {
		return accessTokenInfo{}, err
	}

	// Calculate the time at which the accessTokenInfo will expire from the expires_in seconds
	// from the response.
	expiresAt := time.Now().UTC().Add(time.Duration(tokenResponse.ExpiresIn) * time.Second)

	return accessTokenInfo{
		AccessToken: tokenResponse.AccessToken,
		ExpiresAt:   ExpiresAt(expiresAt),
	}, nil
}

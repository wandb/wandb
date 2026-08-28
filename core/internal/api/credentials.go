package api

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
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

	maxTokenResponseBytes = 1 << 20

	// tokenExpiryBuffer is how far ahead of a token's actual expiration
	// it is treated as expired, so that a request never starts with a
	// token that expires mid-flight.
	tokenExpiryBuffer = 5 * time.Minute
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
		clientOptions := ClientOptions{
			RetryMax:        TokenExchangeRetryMax,
			RetryWaitMin:    tokenExchangeRetryWaitMin,
			RetryWaitMax:    tokenExchangeRetryWaitMax,
			RetryPolicy:     TokenExchangeRetryPolicy,
			NonRetryTimeout: tokenExchangeAttemptTimeout,

			Proxy:              s.GetProxyFn(),
			ProxyConnectHeader: s.GetProxyConnectHeader(),

			InsecureDisableSSL: s.IsInsecureDisableSSL(),
			Logger:             logger,
		}
		// The refresh client talks to the third-party IdP: never disable
		// TLS verification or follow redirects for it, and don't retry,
		// since a retried refresh could consume a single-use refresh token.
		refreshOptions := clientOptions
		refreshOptions.RetryMax = 0
		refreshOptions.InsecureDisableSSL = false
		refreshOptions.CheckRedirect = func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		}
		refreshClient := NewClient(refreshOptions)
		clientOptions.PreRetryLayers = httplayers.DefaultHeaders(s.GetExtraHTTPHeaders())
		exchangeClient := NewClient(clientOptions)

		return NewOAuth2CredentialProvider(
			s.GetBaseURL(),
			s.GetIdentityTokenFile(),
			s.GetCredentialsFile(),
			exchangeClient,
			refreshClient,
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
	refreshHTTPClient RetryableClient,
	logger *slog.Logger,
) (CredentialProvider, error) {
	// Fail fast on misconfiguration. The token itself is re-read from the
	// file for each exchange: identity tokens are often short-lived and
	// re-minted to the same path, so the value read here may not stay valid
	// for the lifetime of the provider.
	identity, err := loadIdentityToken(identityTokenFilePath)
	if err != nil {
		return nil, err
	}
	if err := validateIdentityTokenHost(identity, baseURL); err != nil {
		return nil, err
	}
	return &oauth2CredentialProvider{
		baseURL:               baseURL,
		identityTokenFilePath: identityTokenFilePath,
		credentialsFilePath:   credentialsFilePath,
		httpClient:            httpClient,
		refreshHTTPClient:     refreshHTTPClient,
		tokenMu:               &sync.RWMutex{},
		identityTokenMu:       lockedfile.MutexAt(identityTokenFilePath + ".lock"),
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

// IdentityTokenExpiredError means an expired ID token cannot be refreshed.
type IdentityTokenExpiredError struct{}

func (e *IdentityTokenExpiredError) Error() string {
	return "identity token expired and cannot be refreshed;" +
		" provide a new identity token or run `wandb login sso`"
}

// PermanentError returns true: this cannot be resolved by retrying.
func (e *IdentityTokenExpiredError) PermanentError() bool { return true }

// IdentityTokenRefreshError is a definitive rejection of a refresh_token
// exchange by the IdP, like a revoked or expired refresh token.
type IdentityTokenRefreshError struct {
	// StatusCode is the HTTP status returned by the token endpoint.
	StatusCode int

	// Detail is the OAuth error code and description.
	Detail string
}

func (e *IdentityTokenRefreshError) Error() string {
	detail := e.Detail
	if e.StatusCode != 0 {
		detail = fmt.Sprintf("HTTP %d: %s", e.StatusCode, e.Detail)
	}
	return "failed to refresh identity token: " + detail +
		"; run `wandb login sso` to reauthenticate"
}

// PermanentError returns true: retrying with the same refresh token
// cannot succeed.
func (e *IdentityTokenRefreshError) PermanentError() bool { return true }

func oauthErrorDetail(body []byte) string {
	var response struct {
		Error            string `json:"error"`
		ErrorDescription string `json:"error_description"`
	}
	if json.Unmarshal(body, &response) != nil || response.Error == "" {
		return "OAuth error response"
	}
	if response.ErrorDescription == "" {
		return response.Error
	}
	return response.Error + ": " + response.ErrorDescription
}

func shouldRefreshIdentityToken(err *TokenExchangeError) bool {
	if err.StatusCode != http.StatusBadRequest &&
		err.StatusCode != http.StatusUnauthorized {
		return false
	}

	var response struct {
		Error string `json:"error"`
	}
	if json.Unmarshal([]byte(err.Body), &response) != nil {
		return false
	}
	return response.Error == "invalid_grant" || response.Error == "invalid_token"
}

// isExchangeRejection reports whether the token endpoint's status is a
// definitive rejection of the exchange, like an invalid or expired
// identity token, unknown user or bad audience. 429 and 5xx responses
// may be transient, so they are not rejections.
func isExchangeRejection(statusCode int) bool {
	return statusCode >= 400 && statusCode < 500 &&
		statusCode != http.StatusRequestTimeout &&
		statusCode != http.StatusTooEarly &&
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

// identityToken is the JSON schema written by `wandb login sso`.
type identityToken struct {
	IDToken       string `json:"id_token"`
	RefreshToken  string `json:"refresh_token,omitempty"`
	TokenEndpoint string `json:"token_endpoint,omitempty"`
	ClientID      string `json:"client_id,omitempty"`
	Host          string `json:"host,omitempty"`
}

// loadIdentityToken supports both legacy bare JWTs and the JSON schema.
func loadIdentityToken(path string) (identityToken, error) {
	contents, err := os.ReadFile(path)
	if err != nil {
		return identityToken{}, fmt.Errorf(
			"api: failed to read identity token file: %w", err)
	}

	// Strip surrounding whitespace, like the trailing newline written
	// by `echo` and most editors, which would otherwise be sent as
	// part of the token.
	raw := strings.TrimSpace(string(contents))
	if raw == "" {
		return identityToken{}, errors.New("api: identity token file is empty")
	}

	if strings.HasPrefix(raw, "{") {
		var token identityToken
		if err := json.Unmarshal([]byte(raw), &token); err != nil {
			return identityToken{}, fmt.Errorf(
				"api: invalid JSON identity token file: %w", err)
		}
		if token.IDToken == "" {
			return identityToken{}, errors.New(
				"api: JSON identity token file has no id_token")
		}
		if token.RefreshToken != "" {
			if token.TokenEndpoint == "" {
				return identityToken{}, errors.New(
					"api: JSON identity token file has no token_endpoint")
			}
			if err := validateTokenEndpoint(token.TokenEndpoint); err != nil {
				return identityToken{}, err
			}
		}
		return token, nil
	}

	return identityToken{IDToken: raw}, nil
}

func validateIdentityTokenHost(token identityToken, baseURL string) error {
	if token.Host != "" &&
		strings.TrimRight(token.Host, "/") != strings.TrimRight(baseURL, "/") {
		return fmt.Errorf(
			"api: identity token is for %s, not %s", token.Host, baseURL)
	}
	return nil
}

func validateTokenEndpoint(rawURL string) error {
	endpoint, err := url.Parse(rawURL)
	if err != nil || endpoint.Host == "" {
		return errors.New("api: token_endpoint must be an absolute HTTP(S) URL")
	}
	ip := net.ParseIP(endpoint.Hostname())
	isLoopback := endpoint.Hostname() == "localhost" || ip != nil && ip.IsLoopback()
	if endpoint.Scheme != "https" && !(endpoint.Scheme == "http" && isLoopback) {
		return errors.New("api: token_endpoint must use HTTPS")
	}
	if endpoint.User != nil || endpoint.Fragment != "" {
		return errors.New(
			"api: token_endpoint must not include credentials or a fragment")
	}
	return nil
}

// writeIdentityToken atomically replaces the identity token file.
func writeIdentityToken(path string, token identityToken) error {
	data, err := json.MarshalIndent(token, "", "  ")
	if err != nil {
		return fmt.Errorf("api: failed to encode identity token: %w", err)
	}

	temp, err := os.CreateTemp(filepath.Dir(path), "."+filepath.Base(path)+".*")
	if err != nil {
		return fmt.Errorf("api: failed to create identity token file: %w", err)
	}
	tempPath := temp.Name()
	defer func() { _ = os.Remove(tempPath) }()

	if err := temp.Chmod(0o600); err != nil {
		_ = temp.Close()
		return fmt.Errorf("api: failed to secure identity token file: %w", err)
	}
	if _, err := temp.Write(data); err != nil {
		_ = temp.Close()
		return fmt.Errorf("api: failed to write identity token file: %w", err)
	}
	if err := temp.Sync(); err != nil {
		_ = temp.Close()
		return fmt.Errorf("api: failed to sync identity token file: %w", err)
	}
	if err := temp.Close(); err != nil {
		return fmt.Errorf("api: failed to close identity token file: %w", err)
	}
	if err := os.Rename(tempPath, path); err != nil {
		// Replacing an existing file with Rename is not supported on every OS.
		if runtime.GOOS != "windows" {
			return fmt.Errorf("api: failed to replace identity token file: %w", err)
		}
		if err := os.WriteFile(path, data, 0o600); err != nil {
			return fmt.Errorf("api: failed to write identity token file: %w", err)
		}
		if err := os.Chmod(path, 0o600); err != nil {
			return fmt.Errorf("api: failed to secure identity token file: %w", err)
		}
	}

	return nil
}

func readTokenResponseBody(body io.Reader) ([]byte, error) {
	data, err := io.ReadAll(io.LimitReader(body, maxTokenResponseBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) > maxTokenResponseBytes {
		return nil, errors.New("api: token response exceeds 1 MiB")
	}
	return data, nil
}

// jwtExpiry returns a JWT's "exp" claim as a time, or ok=false if token
// is not a well-formed JWT or carries no exp claim.
//
// This decodes only the token's payload segment, with no signature
// verification: it is a local optimization to decide whether an
// id_token is worth refreshing before spending a round trip on it. The
// W&B server's response to the actual exchange remains the source of
// truth.
func jwtExpiry(token string) (exp time.Time, ok bool) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return time.Time{}, false
	}

	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return time.Time{}, false
	}

	var claims struct {
		Exp int64 `json:"exp"`
	}
	if err := json.Unmarshal(payload, &claims); err != nil || claims.Exp == 0 {
		return time.Time{}, false
	}

	return time.Unix(claims.Exp, 0), true
}

// isIdentityTokenExpiring reports whether idToken's local "exp" claim is
// at or within tokenExpiryBuffer of now. A token whose expiry cannot be
// determined locally is treated as not expiring, so that a decoding
// failure never blocks an exchange that the server might still accept.
func isIdentityTokenExpiring(idToken string) bool {
	exp, ok := jwtExpiry(idToken)
	return ok && time.Until(exp) <= tokenExpiryBuffer
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

	// The client used with the third-party IdP.
	refreshHTTPClient RetryableClient

	tokenMu *sync.RWMutex

	identityTokenMu *lockedfile.Mutex

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
	return time.Until(time.Time(c.ExpiresAt)) <= tokenExpiryBuffer
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

// Reads the identity token from a file, refreshing it first if it looks
// expired, and exchanges it for an access token from the authorization
// server using the JWT Bearer flow defined in OAuth RFC 7523. The access
// token is then returned with its expiration time.
func (c *oauth2CredentialProvider) fetchAccessToken(
	ctx context.Context,
) (accessTokenInfo, error) {
	// Read the file for each exchange: short-lived identity tokens are
	// re-minted to the same path, and an exchange must use the current
	// file contents rather than the token present at startup.
	identity, err := loadIdentityToken(c.identityTokenFilePath)
	if err != nil {
		return accessTokenInfo{}, err
	}
	if err := validateIdentityTokenHost(identity, c.baseURL); err != nil {
		return accessTokenInfo{}, err
	}

	refreshed := false
	if isIdentityTokenExpiring(identity.IDToken) {
		if identity.RefreshToken == "" || identity.TokenEndpoint == "" {
			return accessTokenInfo{}, &IdentityTokenExpiredError{}
		}
		if identity, err = c.refreshIdentityToken(ctx, identity); err != nil {
			return accessTokenInfo{}, err
		}
		refreshed = true
	}

	token, err := c.exchangeIdentityToken(ctx, identity.IDToken)

	var exchangeErr *TokenExchangeError
	if err == nil ||
		!errors.As(err, &exchangeErr) ||
		refreshed ||
		!shouldRefreshIdentityToken(exchangeErr) {
		return token, err
	}

	// The identity token looked valid locally but W&B rejected it anyway
	// (e.g. it was actually expired, revoked, or the clocks disagree). If
	// there's a refresh token we haven't tried yet, refresh once and
	// retry the exchange; otherwise the server's rejection is final --
	// there's nothing to be gained by converting it to a different error.
	if identity.RefreshToken == "" || identity.TokenEndpoint == "" {
		return accessTokenInfo{}, err
	}
	if identity, err = c.refreshIdentityToken(ctx, identity); err != nil {
		return accessTokenInfo{}, err
	}
	return c.exchangeIdentityToken(ctx, identity.IDToken)
}

// refreshIdentityToken exchanges current.RefreshToken for a new id_token
// (and usually a new refresh_token) at the IdP's token endpoint, via the
// OAuth2 refresh_token grant (RFC 6749 section 6), then rewrites the
// identity token file so the new tokens are available to any process
// reading the same file.
func (c *oauth2CredentialProvider) refreshIdentityToken(
	ctx context.Context,
	current identityToken,
) (identityToken, error) {
	unlock, err := c.identityTokenMu.Lock()
	if err != nil {
		return identityToken{}, fmt.Errorf("api: failed to lock identity token file: %w", err)
	}
	defer unlock()

	latest, err := loadIdentityToken(c.identityTokenFilePath)
	if err != nil {
		return identityToken{}, err
	}
	if err := validateIdentityTokenHost(latest, c.baseURL); err != nil {
		return identityToken{}, err
	}
	if latest.IDToken != current.IDToken || latest.RefreshToken != current.RefreshToken {
		current = latest
		if !isIdentityTokenExpiring(current.IDToken) {
			return current, nil
		}
	}
	if current.RefreshToken == "" || current.TokenEndpoint == "" {
		return identityToken{}, &IdentityTokenExpiredError{}
	}

	// This is its own subtask for the same reason the exchange below is:
	// it serves every request waiting on the token, not just the one
	// whose context this is.
	op := wboperation.Get(ctx).Subtask("refreshing identity token")
	defer op.Finish()

	ctx, cancel := context.WithTimeout(op.Context(ctx), tokenExchangeTimeout)
	defer cancel()

	form := url.Values{
		"grant_type":    {"refresh_token"},
		"refresh_token": {current.RefreshToken},
	}
	if current.ClientID != "" {
		form.Set("client_id", current.ClientID)
	}

	req, err := retryablehttp.NewRequestWithContext(
		ctx, http.MethodPost, current.TokenEndpoint, []byte(form.Encode()))
	if err != nil {
		return identityToken{}, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := c.refreshHTTPClient.Do(req)
	if err != nil {
		return identityToken{}, &IdentityTokenRefreshError{
			Detail: err.Error(),
		}
	}
	defer func() {
		_ = resp.Body.Close()
	}()

	body, err := readTokenResponseBody(resp.Body)
	if err != nil {
		return identityToken{}, &IdentityTokenRefreshError{Detail: err.Error()}
	}

	if resp.StatusCode != http.StatusOK {
		return identityToken{}, &IdentityTokenRefreshError{
			StatusCode: resp.StatusCode,
			Detail:     oauthErrorDetail(body),
		}
	}

	var refreshed struct {
		IDToken      string `json:"id_token"`
		RefreshToken string `json:"refresh_token"`
	}
	if err := json.Unmarshal(body, &refreshed); err != nil {
		return identityToken{}, &IdentityTokenRefreshError{
			Detail: "invalid response: " + err.Error(),
		}
	}
	if refreshed.IDToken == "" {
		return identityToken{}, &IdentityTokenRefreshError{
			Detail: "response did not include an id_token",
		}
	}

	next := identityToken{
		IDToken:       refreshed.IDToken,
		RefreshToken:  refreshed.RefreshToken,
		TokenEndpoint: current.TokenEndpoint,
		ClientID:      current.ClientID,
		Host:          current.Host,
	}
	if next.RefreshToken == "" {
		// Not every IdP rotates the refresh token on use.
		next.RefreshToken = current.RefreshToken
	}

	if err := writeIdentityToken(c.identityTokenFilePath, next); err != nil {
		return identityToken{}, &IdentityTokenRefreshError{
			Detail: "failed to persist rotated credentials: " + err.Error(),
		}
	}

	return next, nil
}

// exchangeIdentityToken exchanges idToken for an access token using the
// JWT Bearer flow defined in OAuth RFC 7523.
func (c *oauth2CredentialProvider) exchangeIdentityToken(
	ctx context.Context,
	idToken string,
) (accessTokenInfo, error) {
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
		url.QueryEscape(idToken),
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

	body, err := readTokenResponseBody(resp.Body)
	if err != nil {
		return accessTokenInfo{}, err
	}

	if resp.StatusCode != http.StatusOK {
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
	if err := json.Unmarshal(body, &tokenResponse); err != nil {
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

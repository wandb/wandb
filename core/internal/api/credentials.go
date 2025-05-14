package api

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/settings"
)

// CredentialProvider adds credentials to HTTP requests.
type CredentialProvider interface {
	// Apply sets the appropriate authorization headers or parameters on the
	// HTTP request.
	Apply(req *http.Request) error
}

// NewCredentialProvider creates a new credential provider based on the SDK
// settings. Settings for JWT authentication are prioritized above API key
// authentication.
func NewCredentialProvider(
	settings *settings.Settings,
	logger *slog.Logger,
) (CredentialProvider, error) {
	if settings.GetIdentityTokenFile() != "" {
		return NewOAuth2CredentialProvider(
			settings.GetBaseURL(),
			settings.GetIdentityTokenFile(),
			settings.GetCredentialsFile(),
			logger,
		)
	}
	return NewAPIKeyCredentialProvider(settings)
}

var _ CredentialProvider = &apiKeyCredentialProvider{}

type apiKeyCredentialProvider struct {
	// The W&B API key
	apiKey string
}

// NewAPIKeyCredentialProvider validates the presence of an API key and
// returns a new APIKeyCredentialProvider. Returns an error if the API key is unavailable.
func NewAPIKeyCredentialProvider(
	settings *settings.Settings,
) (CredentialProvider, error) {
	if err := settings.EnsureAPIKey(); err != nil {
		return nil, fmt.Errorf("api: couldn't get API key: %v", err)
	}

	return &apiKeyCredentialProvider{
		apiKey: settings.GetAPIKey(),
	}, nil
}

// Apply sets the API key in the Authorization header of the request using
// HTTP Basic Authentication. The API key is used as the password,
// while the username is left empty.
func (c *apiKeyCredentialProvider) Apply(req *http.Request) error {
	req.Header.Set(
		"Authorization",
		"Basic "+base64.StdEncoding.EncodeToString(
			[]byte("api:"+c.apiKey)),
	)
	return nil
}

var _ CredentialProvider = &oauth2CredentialProvider{}

// OAuth2CredentialProvider creates a credentials provider that exchanges a JWT
// for an access token via an authorization server. The access token is then used
// to authenticate API requests.
//
// The JWT is supplied via a file path that is passed in as an environment
// variable. When the OAuth2CredentialProvider is applied, it exchanges the JWT
// for an access token. It then attempts to save it to the credentials file along
// with its expiration. The expiration is checked each time the access token is
// used, and refreshed if it is at or near expiration.
func NewOAuth2CredentialProvider(
	baseURL string,
	identityTokenFilePath string,
	credentialsFilePath string,
	logger *slog.Logger,
) (CredentialProvider, error) {
	identityToken, err := os.ReadFile(identityTokenFilePath)
	if err != nil {
		return nil, fmt.Errorf("api: failed to read identity token file: %v", err)
	}
	return &oauth2CredentialProvider{
		baseURL:             baseURL,
		credentialsFilePath: credentialsFilePath,
		tokenMu:             &sync.RWMutex{},
		identityToken:       string(identityToken),
		logger:              logger,
	}, nil
}

type oauth2CredentialProvider struct {
	// The URL of the W&B API.
	baseURL string

	// The identity token supplied via the identity token file path.
	identityToken string

	// The access token and its metadata.
	tokenInfo accessTokenInfo

	// The file path to the access token and its metadata.
	credentialsFilePath string

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

// Apply Checks if the access token is expiring, and fetches a new one if so.
// It then supplies the access token to the request via the Authorization header
// as a Bearer token.
func (c *oauth2CredentialProvider) Apply(req *http.Request) error {
	if c.shouldRefreshToken() {
		err := c.loadCredentials()
		if err != nil {
			return err
		}
	}

	req.Header.Set(
		"Authorization",
		"Bearer "+c.tokenInfo.AccessToken,
	)
	return nil
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
func (c *oauth2CredentialProvider) loadCredentials() error {
	c.tokenMu.Lock()
	defer c.tokenMu.Unlock()

	// if the access token has already been refreshed, return early
	if !c.tokenInfo.IsTokenExpiring() {
		return nil
	}

	credsFile, ok := c.tryLoadCredentialsFromFile()
	if ok {
		accessToken, ok := credsFile.Credentials[c.baseURL]
		if ok && !accessToken.IsTokenExpiring() {
			c.tokenInfo = accessToken
			return nil
		}
	}

	token, err := c.fetchAccessToken()
	if err != nil {
		return fmt.Errorf("api: couldn't fetch access token: %v", err)
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
	err = os.WriteFile(c.credentialsFilePath, file, 0600)
	if err != nil {
		c.logger.Warn("failed to write credentials file", "error", err.Error())
	}
}

// Reads the identity token from a file and exchanges it for
// an access token from the authorization server using the JWT Bearer flow defined
// in OAuth RFC 7523. The access token is then returned with its expiration time.
func (c *oauth2CredentialProvider) fetchAccessToken() (accessTokenInfo, error) {
	url := fmt.Sprintf("%s/oidc/token", c.baseURL)
	data := fmt.Sprintf("grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=%s", c.identityToken)
	req, err := http.NewRequest("POST", url, strings.NewReader(data))
	if err != nil {
		return accessTokenInfo{}, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := http.DefaultClient.Do(req)
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
		return accessTokenInfo{}, fmt.Errorf("failed to retrieve access token: %s", string(body))
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

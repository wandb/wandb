package api

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/wandb/wandb/core/internal/settings"
)

// CredentialProvider adds Credentials to HTTP requests.
type CredentialProvider interface {
	// Apply sets the appropriate authorization headers or parameters on the
	// HTTP request.
	Apply(req *http.Request) error
}

func NewCredentialProvider(
	settings *settings.Settings,
) (CredentialProvider, error) {
	if settings.GetIdentityTokenFile() != "" {
		return NewOAuth2CredentialProvider(settings)
	}
	return NewAPIKeyCredentialProvider(settings)
}

var _ CredentialProvider = &apiKeyCredentialProvider{}

type apiKeyCredentialProvider struct {
	apiKey string
}

func NewAPIKeyCredentialProvider(
	settings *settings.Settings,
) (CredentialProvider, error) {
	if err := settings.EnsureAPIKey(); err != nil {
		return nil, fmt.Errorf("couldn't get API key: %v", err)
	}

	return &apiKeyCredentialProvider{
		apiKey: settings.GetAPIKey(),
	}, nil
}

func (c *apiKeyCredentialProvider) Apply(req *http.Request) error {
	req.Header.Set(
		"Authorization",
		"Basic "+base64.StdEncoding.EncodeToString(
			[]byte("api:"+c.apiKey)),
	)
	return nil
}

var _ CredentialProvider = &oauth2CredentialProvider{}

func NewOAuth2CredentialProvider(
	settings *settings.Settings,
) (CredentialProvider, error) {
	return &oauth2CredentialProvider{
		baseURL:               settings.GetBaseURL(),
		identityTokenFilePath: settings.GetIdentityTokenFile(),
		credentialsFilePath:   settings.GetCredentialsFile(),
	}, nil
}

type oauth2CredentialProvider struct {
	baseURL               string
	identityTokenFilePath string
	credentialsFilePath   string
	token                 tokenInfo
}

type tokenInfo struct {
	ExpiresIn   float64 `json:"expires_in"`
	AccessToken string  `json:"access_token"`
}

func (c *tokenInfo) IsTokenExpiring() bool {
	expiresAt := time.Now().UTC().Add(time.Second * time.Duration(c.ExpiresIn))
	return time.Until(expiresAt) <= time.Minute*5
}

func (c *oauth2CredentialProvider) Apply(req *http.Request) error {
	if c.token.IsTokenExpiring() {
		if err := c.loadCredentials(); err != nil {
			return err
		}
	}
	req.Header.Set(
		"Authorization",
		"Bearer "+c.token.AccessToken,
	)
	return nil
}

// loadCredentials attempts to load an access token from the credentials file.
// If the credentials file does not exist, it creates it.
func (c *oauth2CredentialProvider) loadCredentials() error {
	_, err := os.Stat(c.credentialsFilePath)
	if os.IsNotExist(err) {
		err = c.writeCredentialsFile()
	}
	if err != nil {
		return err
	}

	return c.loadCredentialsFromFile()
}

type credentialsFile struct {
	Credentials map[string]tokenInfo `json:"credentials"`
}

// loadCredentialsFromFile loads the access token from the credentials file. If
// the access token does not exist for the give base url, it fetches a new one
// from the server, and saves it to the credentials file
func (c *oauth2CredentialProvider) loadCredentialsFromFile() error {
	file, err := os.ReadFile(c.credentialsFilePath)
	if err != nil {
		return fmt.Errorf("failed to read credentials file: %v", err)
	}

	var credsFile credentialsFile
	if err := json.Unmarshal(file, &credsFile); err != nil {
		return fmt.Errorf("failed to read credentials file: %v", err)
	}

	creds, ok := credsFile.Credentials[c.baseURL]

	if !ok || creds.IsTokenExpiring() {
		newCreds, err := c.createAccessToken()
		if err != nil {
			return err
		}
		credsFile.Credentials[c.baseURL] = *newCreds
		updatedFile, err := json.MarshalIndent(creds, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to update credentials file: %v", err)
		}
		err = os.WriteFile(c.credentialsFilePath, updatedFile, 0600)
		if err != nil {
			return fmt.Errorf("failed to update credentials file: %v", err)
		}
		c.token = *newCreds
	} else {
		c.token = creds
	}

	return nil
}

// writeCredentialsFile obtains an access token from the server and writes it to
// the credentials file
func (c *oauth2CredentialProvider) writeCredentialsFile() error {
	token, err := c.createAccessToken()
	if err != nil {
		return err
	}

	data := credentialsFile{
		Credentials: map[string]tokenInfo{
			c.baseURL: *token,
		},
	}

	file, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to write credentials file: %v", err)
	}

	err = os.WriteFile(c.credentialsFilePath, file, 0600)
	if err != nil {
		return fmt.Errorf("failed to write credentials file: %v", err)
	}

	return nil
}

// createAccessToken exchanges an identity token for an access token from the server.
func (c *oauth2CredentialProvider) createAccessToken() (*tokenInfo, error) {
	token, err := os.ReadFile(c.identityTokenFilePath)
	if err != nil {
		return nil, fmt.Errorf("failed to read identity token file: %v", err)
	}

	url := fmt.Sprintf("%s/oidc/token", c.baseURL)
	data := fmt.Sprintf("grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=%s", token)
	req, err := http.NewRequest("POST", url, strings.NewReader(data))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return nil, err
		}
		return nil, fmt.Errorf("failed to retrieve access token: %s", string(body))
	}

	var tokenInfo tokenInfo
	if err := json.NewDecoder(resp.Body).Decode(&tokenInfo); err != nil {
		return nil, err
	}

	return &tokenInfo, nil
}

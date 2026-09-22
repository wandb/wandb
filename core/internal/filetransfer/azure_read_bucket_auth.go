//go:build cloud_http

package filetransfer

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"net/http"
	"net/url"
	"slices"
	"strconv"
	"strings"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
)

type azureReadAuth int

const (
	azureReadDefaultCredential azureReadAuth = iota
	azureReadSharedKey
	azureReadSAS
)

type azureReadConfiguration struct {
	endpoint string
	account  string
	key      string
	auth     azureReadAuth
}

// TensorBoard opens bare azblob://container URLs. Match the environment
// precedence of gocloud's azureblob driver, including its connection-string alias.
func azureReadConfigFromEnv(getenv func(string) string) (azureReadConfiguration, error) {
	connection := getenv("AZURE_STORAGE_CONNECTION_STRING")
	if connection == "" {
		connection = getenv("AZURE_STORAGEBLOB_CONNECTIONSTRING")
	}
	account, protocol := getenv("AZURE_STORAGE_ACCOUNT"), getenv("AZURE_STORAGE_PROTOCOL")
	for part := range strings.SplitSeq(connection, ";") {
		key, value, ok := strings.Cut(part, "=")
		if ok && key == "AccountName" && account == "" {
			account = value
		}
		if ok && key == "DefaultEndpointsProtocol" && protocol == "" {
			protocol = value
		}
	}
	endpoint, err := azureReadServiceURL(account, protocol, getenv)
	if err != nil {
		return azureReadConfiguration{}, err
	}
	configuration := azureReadConfiguration{endpoint: endpoint, account: account}
	switch {
	case getenv("AZURE_STORAGE_ACCOUNT") != "" && getenv("AZURE_STORAGE_KEY") != "":
		configuration.auth = azureReadSharedKey
		configuration.key = getenv("AZURE_STORAGE_KEY")
	case getenv("AZURE_STORAGE_SAS_TOKEN") != "":
		configuration.auth = azureReadSAS
	case connection != "":
		return azureReadConnectionString(connection)
	}
	return configuration, nil
}

func azureReadServiceURL(account, protocol string, getenv func(string) string) (string, error) {
	if account == "" {
		return "", fmt.Errorf("azure storage account is required")
	}
	if protocol == "" {
		protocol = "https"
	}
	if protocol != "http" && protocol != "https" {
		return "", fmt.Errorf("invalid Azure storage protocol %q", protocol)
	}
	domain := getenv("AZURE_STORAGE_DOMAIN")
	if domain == "" {
		domain = "blob.core.windows.net"
	}
	local, _ := strconv.ParseBool(getenv("AZURE_STORAGE_IS_LOCAL_EMULATOR"))
	cdn, _ := strconv.ParseBool(getenv("AZURE_STORAGE_IS_CDN"))
	var endpoint string
	switch {
	case local || strings.HasPrefix(domain, "localhost") || strings.HasPrefix(domain, "127.0.0.1"):
		endpoint = protocol + "://" + domain + "/" + account
	case cdn:
		endpoint = protocol + "://" + domain
	default:
		endpoint = protocol + "://" + account + "." + domain
	}
	if sas := getenv("AZURE_STORAGE_SAS_TOKEN"); sas != "" {
		endpoint += "?" + sas
	}
	return endpoint, nil
}

func azureReadConnectionString(connection string) (azureReadConfiguration, error) {
	values := map[string]string{}
	for part := range strings.SplitSeq(strings.TrimRight(connection, ";"), ";") {
		key, value, ok := strings.Cut(part, "=")
		if !ok {
			return azureReadConfiguration{}, fmt.Errorf("malformed Azure storage connection string")
		}
		values[key] = value
	}
	endpoint, explicitEndpoint := values["BlobEndpoint"]
	account, hasAccount := values["AccountName"]
	if !explicitEndpoint {
		if !hasAccount {
			return azureReadConfiguration{}, fmt.Errorf(
				"azure connection string requires AccountName or BlobEndpoint",
			)
		}
		protocol, ok := values["DefaultEndpointsProtocol"]
		if !ok {
			protocol = "https"
		}
		suffix, ok := values["EndpointSuffix"]
		if !ok {
			suffix = "core.windows.net"
		}
		endpoint = protocol + "://" + account + ".blob." + suffix
	}
	key, hasKey := values["AccountKey"]
	if hasAccount && hasKey {
		configuration := azureReadConfiguration{
			endpoint: endpoint,
			account:  account,
			key:      key,
			auth:     azureReadSharedKey,
		}
		// The storage SDK treats empty connection-string account/key values
		// as a client without credentials, which can read public containers.
		if account == "" || key == "" {
			configuration.auth = azureReadSAS
		}
		return configuration, nil
	}
	if sas, ok := values["SharedAccessSignature"]; ok {
		return azureReadConfiguration{endpoint: endpoint + "?" + sas, auth: azureReadSAS}, nil
	}
	return azureReadConfiguration{}, fmt.Errorf(
		"azure connection string requires AccountKey or SharedAccessSignature",
	)
}

// Shared Key signing follows the Blob service's REST authorization scheme.
// Keeping it in a per-retry policy signs the final URL, including continuation
// tokens and byte ranges, whenever azcore retries a request.
// https://learn.microsoft.com/en-us/rest/api/storageservices/authorize-with-shared-key
type azureSharedKeyPolicy struct {
	account string
	key     []byte
}

func newAzureSharedKeyPolicy(account, encodedKey string) (*azureSharedKeyPolicy, error) {
	key, err := base64.StdEncoding.DecodeString(encodedKey)
	if err != nil {
		return nil, fmt.Errorf("decode Azure storage account key: %w", err)
	}
	return &azureSharedKeyPolicy{account: account, key: key}, nil
}

func (p *azureSharedKeyPolicy) Do(request *policy.Request) (*http.Response, error) {
	text, err := azureSharedKeyStringToSign(request.Raw(), p.account)
	if err != nil {
		return nil, err
	}
	hash := hmac.New(sha256.New, p.key)
	_, _ = hash.Write([]byte(text))
	signature := base64.StdEncoding.EncodeToString(hash.Sum(nil))
	request.Raw().Header.Set("Authorization", "SharedKey "+p.account+":"+signature)
	return request.Next()
}

func azureSharedKeyStringToSign(request *http.Request, account string) (string, error) {
	contentLength := request.Header.Get("Content-Length")
	if contentLength == "0" {
		contentLength = ""
	}
	fields := []string{request.Method}
	for _, name := range []string{"Content-Encoding", "Content-Language"} {
		fields = append(fields, request.Header.Get(name))
	}
	fields = append(
		fields,
		contentLength,
		request.Header.Get("Content-MD5"),
		request.Header.Get("Content-Type"),
		"",
	)
	for _, name := range []string{"If-Modified-Since", "If-Match", "If-None-Match", "If-Unmodified-Since", "Range"} {
		fields = append(fields, request.Header.Get(name))
	}
	canonicalHeaders := map[string][]string{}
	for name, values := range request.Header {
		name = strings.ToLower(strings.TrimSpace(name))
		if strings.HasPrefix(name, "x-ms-") {
			canonicalHeaders[name] = append(canonicalHeaders[name], values...)
		}
	}
	headerNames := make([]string, 0, len(canonicalHeaders))
	for name := range canonicalHeaders {
		headerNames = append(headerNames, name)
	}
	slices.Sort(headerNames)
	for _, name := range headerNames {
		fields = append(fields, name+":"+strings.Join(canonicalHeaders[name], ","))
	}
	path := request.URL.EscapedPath()
	if path == "" {
		path = "/"
	}
	fields = append(fields, "/"+account+path)
	query, err := url.ParseQuery(request.URL.RawQuery)
	if err != nil {
		return "", fmt.Errorf("invalid Azure query parameters: %w", err)
	}
	queryNames := make([]string, 0, len(query))
	for name := range query {
		queryNames = append(queryNames, name)
	}
	slices.Sort(queryNames)
	for _, name := range queryNames {
		values := query[name]
		slices.Sort(values)
		fields = append(fields, strings.ToLower(name)+":"+strings.Join(values, ","))
	}
	return strings.Join(fields, "\n"), nil
}

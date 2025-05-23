package monitor

import (
	"bufio"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"reflect"
	"strconv"
	"strings"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// DefaultCoreWeaveMetadataBaseURL  = "http://169.254.169.254"
	DefaultCoreWeaveMetadataBaseURL  = "http://127.0.0.1:3000"
	DefaultCoreWeaveMetadataEndpoint = "/api/v2/cloud-init/meta-data"
)

// CoreWeaveInstanceData holds the parsed metadata from the CoreWeave endpoint.
type CoreWeaveInstanceData struct {
	CalicoCleanupAPI    string `meta:"calico_cleanup_api"`
	K8sVersion          string `meta:"k8s_version"`
	TeleportAddress     string `meta:"teleport_address"`
	TeleportRegion      string `meta:"teleport_region"`
	OrgID               string `meta:"org_id"`
	Region              string `meta:"region"`
	FDERaid             bool   `meta:"fde_raid"`
	TeleportClass       string `meta:"teleport_class"`
	EtcHosts            string `meta:"etc_hosts"`
	JoinToken           string `meta:"join_token"`
	ClusterName         string `meta:"cluster_name"`
	RegistryProxyServer string `meta:"registry_proxy_server"`
	CACertHash          string `meta:"ca_cert_hash"`
	TeleportToken       string `meta:"teleport_token"`
	APIServer           string `meta:"apiserver"`
}

// CoreWeaveMetadata is used to capture the metadata about the compute environment
// for jobs running on CoreWeave.
type CoreWeaveMetadata struct {
	// client is the HTTP client used to call the metadata endpoint
	client *retryablehttp.Client

	logger *observability.CoreLogger

	baseURL  *url.URL
	endpoint string
}

type CoreWeaveMetadataParams struct {
	Client *retryablehttp.Client
	Logger *observability.CoreLogger

	// TODO: add these as configurable settings

	// The scheme and hostname for contacting the metadata server,
	// not including a final slash. For example, "http://localhost:8080".
	BaseURL *url.URL

	// The relative path on the server to which to make requests.
	//
	// This must not include the schema and hostname prefix.
	Endpoint string
}

func NewCoreWeaveMetadata(params CoreWeaveMetadataParams) (*CoreWeaveMetadata, error) {
	if params.Client == nil {
		params.Client = retryablehttp.NewClient()
		params.Client.Logger = params.Logger
		params.Client.CheckRetry = retryablehttp.ErrorPropagatedRetryPolicy
		params.Client.RetryMax = DefaultOpenMetricsRetryMax
		params.Client.RetryWaitMin = DefaultOpenMetricsRetryWaitMin
		params.Client.RetryWaitMax = DefaultOpenMetricsRetryWaitMax
		params.Client.HTTPClient.Timeout = DefaultOpenMetricsTimeout
		params.Client.Backoff = clients.ExponentialBackoffWithJitter
	}
	if params.BaseURL == nil {
		baseURL, err := url.Parse(DefaultCoreWeaveMetadataBaseURL)
		if err != nil {
			return nil, err
		}
		params.BaseURL = baseURL
	}
	if params.Endpoint == "" {
		params.Endpoint = DefaultCoreWeaveMetadataEndpoint
	}

	// TODO: call OrganizationCoreWeaveOrganizationID here

	cwm := &CoreWeaveMetadata{
		client:   params.Client,
		logger:   params.Logger,
		baseURL:  params.BaseURL,
		endpoint: params.Endpoint,
	}

	return cwm, nil
}

// Need this for Asset Interface complience
func (cwm *CoreWeaveMetadata) Sample() (*spb.StatsRecord, error) {
	return nil, nil
}

// TODO: convert Get to Probe

func (cwm *CoreWeaveMetadata) Probe() *spb.MetadataRequest {
	return nil
}

//gocyclo:ignore
func (cwm *CoreWeaveMetadata) Get() (*CoreWeaveInstanceData, error) {
	fullURL := cwm.baseURL.JoinPath(cwm.endpoint).String()
	req, err := retryablehttp.NewRequest("GET", fullURL, nil) // Use fullURL here
	if err != nil {
		return nil, fmt.Errorf("coreweave metadata: failed to create request: %w", err)
	}

	if cwm.logger != nil {
		cwm.logger.Debug("coreweave metadata: sending request", "url", fullURL)
	}

	fmt.Println(fullURL)
	fmt.Printf("%+v\n", cwm)

	resp, err := cwm.client.Do(req)
	if err != nil {
		if cwm.logger != nil {
			cwm.logger.Error("coreweave metadata: request failed", "error", err, "url", fullURL)
		}
		return nil, fmt.Errorf("coreweave metadata: request to %s failed: %w", fullURL, err)
	}
	defer func() {
		if resp != nil && resp.Body != nil {
			_, err := io.Copy(io.Discard, resp.Body) // Read and discard remaining body
			if err != nil && cwm.logger != nil {
				cwm.logger.Error("coreweave metadata: error discarding response body", "error", err)
			}
			err = resp.Body.Close()
			if err != nil && cwm.logger != nil {
				cwm.logger.Error("coreweave metadata: error closing response body", "error", err)
			}
		}
	}()

	if resp == nil { // Should not happen if err is nil, but good for defensive programming
		if cwm.logger != nil {
			cwm.logger.Error("coreweave metadata: received nil response without error", "url", fullURL)
		}
		return nil, fmt.Errorf("coreweave metadata: could not fetch metadata from endpoint %s (nil response)", fullURL)
	}

	if cwm.logger != nil {
		cwm.logger.Debug("coreweave metadata: received response", "url", fullURL, "status_code", resp.StatusCode)
	}

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body) // Attempt to read body for error context
		errMsg := fmt.Sprintf("coreweave metadata: unexpected status code %d from %s. Body: %s", resp.StatusCode, fullURL, string(bodyBytes))
		if cwm.logger != nil {
			cwm.logger.Error(errMsg)
		}
		return nil, fmt.Errorf("%s", errMsg)
	}

	data := &CoreWeaveInstanceData{}
	val := reflect.ValueOf(data).Elem()
	typeOfT := val.Type()

	// Create a map for faster field lookup by meta tag
	fieldMap := make(map[string]reflect.Value)
	for i := range val.NumField() {
		field := typeOfT.Field(i)
		tag := field.Tag.Get("meta")
		if tag != "" {
			fieldMap[tag] = val.Field(i)
		}
	}

	scanner := bufio.NewScanner(resp.Body)
	lineNumber := 0
	for scanner.Scan() {
		lineNumber++
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue // Skip empty lines
		}

		parts := strings.SplitN(line, ":", 2)
		if len(parts) != 2 {
			if cwm.logger != nil {
				cwm.logger.Warn("coreweave metadata: malformed line", "line_number", lineNumber, "line_content", line)
			}
			continue // Skip malformed lines
		}

		key := strings.TrimSpace(parts[0])
		value := strings.TrimSpace(parts[1])

		if field, ok := fieldMap[key]; ok && field.CanSet() {
			switch field.Kind() {
			case reflect.String:
				field.SetString(value)
			case reflect.Bool:
				bVal, err := strconv.ParseBool(value)
				if err == nil {
					field.SetBool(bVal)
				} else if cwm.logger != nil {
					cwm.logger.Warn("coreweave metadata: could not parse bool", "key", key, "value", value, "error", err)
				}
			default:
				if cwm.logger != nil {
					cwm.logger.Warn("coreweave metadata: unhandled field type", "key", key, "type", field.Kind())
				}
			}
		} else if cwm.logger != nil {
			cwm.logger.Warn("coreweave metadata: unknown or unsettable field", "key", key, "value", value)
		}
	}

	if err := scanner.Err(); err != nil {
		if cwm.logger != nil {
			cwm.logger.Error("coreweave metadata: error reading response body", "error", err, "url", fullURL)
		}
		return nil, fmt.Errorf("coreweave metadata: error reading response body from %s: %w", fullURL, err)
	}

	if cwm.logger != nil {
		cwm.logger.Info("coreweave metadata: successfully parsed metadata", "data", data)
	}

	return data, nil
}

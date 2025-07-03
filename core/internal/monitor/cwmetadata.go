package monitor

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"reflect"
	"strconv"
	"strings"

	"github.com/Khan/genqlient/graphql"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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

type CoreWeaveMetadataParams struct {
	Client        *retryablehttp.Client
	Logger        *observability.CoreLogger
	GraphqlClient graphql.Client
	Entity        string
	BaseURL       string
	Endpoint      string
}

// CoreWeaveMetadata is used to capture the metadata about the compute environment
// for jobs running on CoreWeave.
type CoreWeaveMetadata struct {
	// HTTP client to communicate with the CoreWeave metadata server.
	client *retryablehttp.Client

	// GraphQL client to communicate with the W&B backend.
	graphqlClient graphql.Client

	// W&B entity to use with the gql.OrganizationCoreWeaveOrganizationID query.
	entity string

	// Internal debug logger.
	logger *observability.CoreLogger

	// The scheme and hostname for contacting the metadata server,
	// not including a final slash. For example, "http://localhost:8080".
	baseURL *url.URL

	// The relative path on the server to which to make requests.
	//
	// This must not include the schema and hostname prefix.
	endpoint string
}

func NewCoreWeaveMetadata(params CoreWeaveMetadataParams) (*CoreWeaveMetadata, error) {
	if params.Logger == nil {
		// No logger - no problem.
		params.Logger = observability.NewNoOpLogger()
	}
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

	baseURL, err := url.Parse(params.BaseURL)
	if err != nil {
		return nil, err
	}
	endpoint := params.Endpoint

	cwm := &CoreWeaveMetadata{
		client:        params.Client,
		graphqlClient: params.GraphqlClient,
		logger:        params.Logger,
		entity:        params.Entity,
		baseURL:       baseURL,
		endpoint:      endpoint,
	}

	return cwm, nil
}

// Sample is a no-op method.
//
// Required for CoreWeaveMetadata to implement the Resource interface.
func (cwm *CoreWeaveMetadata) Sample() (*spb.StatsRecord, error) {
	return nil, nil
}

// Probe collects metadata about the CoreWeave compute environment.
//
// It first checks if the current W&B entity's organization is using
// CoreWeave by querying the W&B backend. If so, it fetches instance
// metadata from the CoreWeave metadata endpoint using the Get method.
func (cwm *CoreWeaveMetadata) Probe(ctx context.Context) *spb.EnvironmentRecord {
	if cwm.graphqlClient == nil {
		cwm.logger.Debug("coreweave metadata: error collecting data", "error", fmt.Errorf("GraphQL client is nil"))
		return nil
	}

	// Check whether this entity's organization is on CoreWeave
	// to limit collecting metadata to the relevant organizations.
	data, err := gql.OrganizationCoreWeaveOrganizationID(
		ctx,
		cwm.graphqlClient,
		cwm.entity,
	)
	if err != nil || data == nil || data.GetEntity() == nil || data.GetEntity().GetOrganization() == nil {
		return nil
	}
	coreWeaveOrgID := data.GetEntity().GetOrganization().GetCoreWeaveOrganizationId()
	if coreWeaveOrgID == nil || *coreWeaveOrgID == "" {
		return nil
	}

	instanceData, err := cwm.Get()
	if err != nil {
		cwm.logger.Error("coreweave metadata: error collecting data", "error", err)
		return nil
	}

	return &spb.EnvironmentRecord{
		Coreweave: &spb.CoreWeaveInfo{
			ClusterName: instanceData.ClusterName,
			OrgId:       instanceData.OrgID,
			Region:      instanceData.Region,
		},
	}
}

// Get fetches and parses metadata from the CoreWeave instance metadata endpoint.
func (cwm *CoreWeaveMetadata) Get() (*CoreWeaveInstanceData, error) {
	fullURL := cwm.baseURL.JoinPath(cwm.endpoint).String()
	req, err := retryablehttp.NewRequest("GET", fullURL, nil) // Use fullURL here
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	cwm.logger.Debug("coreweave metadata: sending request", "url", fullURL)

	resp, err := cwm.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request to %s failed: %w", fullURL, err)
	}
	defer func() {
		if resp != nil && resp.Body != nil {
			_, err := io.Copy(io.Discard, resp.Body) // Read and discard remaining body
			if err != nil {
				cwm.logger.Error("coreweave metadata: error discarding response body", "error", err)
			}
			err = resp.Body.Close()
			if err != nil {
				cwm.logger.Error("coreweave metadata: error closing response body", "error", err)
			}
		}
	}()

	if resp == nil { // Should not happen if err is nil, but good for defensive programming.
		return nil, fmt.Errorf("could not fetch metadata from endpoint %s (nil response)", fullURL)
	}

	cwm.logger.Debug("coreweave metadata: received response", "url", fullURL, "status_code", resp.StatusCode)

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body) // Attempt to read body for error context
		errMsg := fmt.Sprintf("unexpected status code %d from %s. Body: %s", resp.StatusCode, fullURL, string(bodyBytes))
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
			cwm.logger.Debug("coreweave metadata: malformed line", "line_number", lineNumber, "line_content", line)
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
				} else {
					cwm.logger.Debug("coreweave metadata: could not parse bool", "key", key, "value", value, "error", err)
				}
			default:
				cwm.logger.Debug("coreweave metadata: unhandled field type", "key", key, "type", field.Kind())
			}
		} else {
			cwm.logger.Debug("coreweave metadata: unknown or unsettable field", "key", key, "value", value)
		}
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("error reading response body from %s: %w", fullURL, err)
	}

	if cwm.logger != nil {
		cwm.logger.Debug("coreweave metadata: successfully parsed metadata", "data", data)
	}

	return data, nil
}

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
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/settings"
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
	GraphqlClient graphql.Client
	Logger        *observability.CoreLogger
	RunHandle     *runhandle.RunHandle
	Settings      *settings.Settings
}

// CoreWeaveMetadata is used to capture the metadata about the compute environment
// for jobs running on CoreWeave.
type CoreWeaveMetadata struct {
	// HTTP client to communicate with the CoreWeave metadata server.
	client *retryablehttp.Client

	// GraphQL client to communicate with the W&B backend.
	graphqlClient graphql.Client

	// Internal debug logger.
	logger *observability.CoreLogger

	// runHandle contains the run's entity, used for the
	// OrganizationCoreWeaveOrganizationID GQL query.
	runHandle *runhandle.RunHandle

	// settings contain the info needed to probe the CoreWeave metadata.
	//
	// Specifically:
	//  - The scheme and hostname for contacting the metadata server,
	//    not including a final slash. For example, "http://localhost:8080".
	//  - The relative path on the server to which to make requests, not
	//    including the schema and hostname prefix.
	settings *settings.Settings
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

	cwm := &CoreWeaveMetadata{
		client:        params.Client,
		graphqlClient: params.GraphqlClient,
		logger:        params.Logger,
		runHandle:     params.RunHandle,
		settings:      params.Settings,
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
		cwm.logger.Debug(
			"cwmetadata: error collecting data",
			"error",
			fmt.Errorf("GraphQL client is nil"),
		)
		return nil
	}

	upserter, err := cwm.runHandle.Upserter()
	if err != nil {
		cwm.logger.CaptureError(fmt.Errorf("cwmetadata: %v", err))
		return nil
	}
	entity := upserter.RunPath().Entity

	// Check whether this entity's organization is on CoreWeave
	// to limit collecting metadata to the relevant organizations.
	data, err := gql.OrganizationCoreWeaveOrganizationID(
		ctx,
		cwm.graphqlClient,
		entity,
	)
	if err != nil || data == nil || data.GetEntity() == nil ||
		data.GetEntity().GetOrganization() == nil {
		return nil
	}
	coreWeaveOrgID := data.GetEntity().GetOrganization().GetCoreWeaveOrganizationId()
	if coreWeaveOrgID == nil || *coreWeaveOrgID == "" {
		return nil
	}

	instanceData, err := cwm.Get()
	if err != nil {
		cwm.logger.Error("cwmetadata: error collecting data", "error", err)
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
	resp, err := cwm.fetchMetadata()
	if err != nil {
		return nil, err
	}
	defer cwm.closeResponse(resp)

	if err := cwm.validateResponse(resp); err != nil {
		return nil, err
	}

	return cwm.parseResponse(resp.Body)
}

// fetchMetadata makes the HTTP request to the CoreWeave metadata endpoint.
func (cwm *CoreWeaveMetadata) fetchMetadata() (*http.Response, error) {
	fullURL, err := cwm.buildURL()
	if err != nil {
		return nil, fmt.Errorf("failed to build URL: %w", err)
	}

	req, err := retryablehttp.NewRequest("GET", fullURL, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	cwm.logger.Debug("cwmetadata: sending request", "url", fullURL)

	resp, err := cwm.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request to %s failed: %w", fullURL, err)
	}

	if resp == nil {
		return nil, fmt.Errorf("could not fetch metadata from endpoint %s (nil response)", fullURL)
	}

	cwm.logger.Debug(
		"cwmetadata: received response",
		"url", fullURL,
		"status_code", resp.StatusCode,
	)
	return resp, nil
}

// buildURL constructs the full URL for the metadata endpoint.
func (cwm *CoreWeaveMetadata) buildURL() (string, error) {
	baseURL, err := url.Parse(cwm.settings.GetStatsCoreWeaveMetadataBaseURL())
	if err != nil {
		return "", fmt.Errorf("failed to parse coreweave metadata baseurl: %w", err)
	}

	endpoint := cwm.settings.GetStatsCoreWeaveMetadataEndpoint()
	return baseURL.JoinPath(endpoint).String(), nil
}

// validateResponse checks if the HTTP response is valid.
func (cwm *CoreWeaveMetadata) validateResponse(resp *http.Response) error {
	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("unexpected status code %d. Body: %s", resp.StatusCode, string(bodyBytes))
	}
	return nil
}

// closeResponse properly closes the response body.
func (cwm *CoreWeaveMetadata) closeResponse(resp *http.Response) {
	if resp != nil && resp.Body != nil {
		_, err := io.Copy(io.Discard, resp.Body)
		if err != nil {
			cwm.logger.Error("cwmetadata: error discarding response body", "error", err)
		}
		if err := resp.Body.Close(); err != nil {
			cwm.logger.Error("cwmetadata: error closing response body", "error", err)
		}
	}
}

// parseResponse parses the metadata from the response body.
func (cwm *CoreWeaveMetadata) parseResponse(body io.Reader) (*CoreWeaveInstanceData, error) {
	data := &CoreWeaveInstanceData{}
	fieldMap := cwm.buildFieldMap(data)

	scanner := bufio.NewScanner(body)
	lineNumber := 0

	for scanner.Scan() {
		lineNumber++
		cwm.parseLine(scanner.Text(), lineNumber, fieldMap)
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("error reading response body: %w", err)
	}

	cwm.logger.Debug("cwmetadata: successfully parsed metadata", "data", data)
	return data, nil
}

// buildFieldMap creates a map of field names to reflection values for faster lookup.
func (cwm *CoreWeaveMetadata) buildFieldMap(data *CoreWeaveInstanceData) map[string]reflect.Value {
	fieldMap := make(map[string]reflect.Value)
	val := reflect.ValueOf(data).Elem()
	typeOfT := val.Type()

	for i := range val.NumField() {
		field := typeOfT.Field(i)
		if tag := field.Tag.Get("meta"); tag != "" {
			fieldMap[tag] = val.Field(i)
		}
	}
	return fieldMap
}

// parseLine parses a single line of metadata and updates the corresponding field.
func (cwm *CoreWeaveMetadata) parseLine(
	line string,
	lineNumber int,
	fieldMap map[string]reflect.Value,
) {
	line = strings.TrimSpace(line)
	if line == "" {
		return
	}

	parts := strings.SplitN(line, ":", 2)
	if len(parts) != 2 {
		cwm.logger.Debug(
			"cwmetadata: malformed line",
			"line_number", lineNumber,
			"line_content", line,
		)
		return
	}

	key := strings.TrimSpace(parts[0])
	value := strings.TrimSpace(parts[1])

	field, ok := fieldMap[key]
	if !ok || !field.CanSet() {
		cwm.logger.Debug("cwmetadata: unknown or unsettable field", "key", key, "value", value)
		return
	}

	cwm.setFieldValue(field, key, value)
}

// setFieldValue sets the value of a field based on its type.
func (cwm *CoreWeaveMetadata) setFieldValue(field reflect.Value, key, value string) {
	switch field.Kind() {
	case reflect.String:
		field.SetString(value)
	case reflect.Bool:
		if bVal, err := strconv.ParseBool(value); err == nil {
			field.SetBool(bVal)
		} else {
			cwm.logger.Debug(
				"cwmetadata: could not parse bool",
				"key", key,
				"value", value,
				"error", err,
			)
		}
	default:
		cwm.logger.Debug("cwmetadata: unhandled field type", "key", key, "type", field.Kind())
	}
}

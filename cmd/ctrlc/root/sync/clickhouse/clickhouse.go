package clickhouse

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

type ClickhouseEndpointResponse struct {
	Protocol string `json:"protocol"`
	Host     string `json:"host"`
	Port     int    `json:"port"`
	Username string `json:"username"`
}

type IPAccessListItem struct {
	Source      string `json:"source"`
	Description string `json:"description"`
}

type ClickHouseConfigResponse struct {
	ID                              string                       `json:"id"`
	Name                            string                       `json:"name"`
	Provider                        string                       `json:"provider"`
	Region                          string                       `json:"region"`
	State                           string                       `json:"state"`
	Endpoints                       []ClickhouseEndpointResponse `json:"endpoints"`
	Tier                            string                       `json:"tier"`
	MinTotalMemoryGb                int                          `json:"minTotalMemoryGb"`
	MaxTotalMemoryGb                int                          `json:"maxTotalMemoryGb"`
	MinReplicaMemoryGb              int                          `json:"minReplicaMemoryGb"`
	MaxReplicaMemoryGb              int                          `json:"maxReplicaMemoryGb"`
	NumReplicas                     int                          `json:"numReplicas"`
	IdleScaling                     bool                         `json:"idleScaling"`
	IdleTimeoutMinutes              int                          `json:"idleTimeoutMinutes"`
	IPAccessList                    []IPAccessListItem           `json:"ipAccessList"`
	CreatedAt                       string                       `json:"createdAt"`
	EncryptionKey                   string                       `json:"encryptionKey"`
	EncryptionAssumedRoleIdentifier string                       `json:"encryptionAssumedRoleIdentifier"`
	IamRole                         string                       `json:"iamRole"`
	PrivateEndpointIds              []string                     `json:"privateEndpointIds"`
	AvailablePrivateEndpointIds     []string                     `json:"availablePrivateEndpointIds"`
	DataWarehouseId                 string                       `json:"dataWarehouseId"`
	IsPrimary                       bool                         `json:"isPrimary"`
	IsReadonly                      bool                         `json:"isReadonly"`
	ReleaseChannel                  string                       `json:"releaseChannel"`
	ByocId                          string                       `json:"byocId"`
	HasTransparentDataEncryption    bool                         `json:"hasTransparentDataEncryption"`
	TransparentDataEncryptionKeyId  string                       `json:"transparentDataEncryptionKeyId"`
	EncryptionRoleId                string                       `json:"encryptionRoleId"`
}

type Connection struct {
	Host     string
	Port     int
	Username string
}

func (c *ClickHouseConfigResponse) GetConnection() Connection {
	for _, endpoint := range c.Endpoints {
		if endpoint.Protocol == "https" {
			return Connection{
				Host:     endpoint.Host,
				Port:     endpoint.Port,
				Username: endpoint.Username,
			}
		}
	}
	for _, endpoint := range c.Endpoints {
		if endpoint.Protocol == "native" {
			return Connection{
				Host:     endpoint.Host,
				Port:     endpoint.Port,
				Username: endpoint.Username,
			}
		}
	}
	return Connection{}
}

type ClickHouseListResponse struct {
	Status    int                        `json:"status"`
	RequestId string                     `json:"requestId"`
	Result    []ClickHouseConfigResponse `json:"result"`
}

func (c *ClickHouseConfigResponse) Struct() map[string]interface{} {
	b, _ := json.Marshal(c)
	var m map[string]interface{}
	json.Unmarshal(b, &m)
	return m
}

type ClickHouseClient struct {
	httpClient     *http.Client
	apiUrl         string
	apiId          string
	apiKey         string
	organizationID string
}

func NewClickHouseClient(apiUrl, apiId, apiKey, organizationID string) *ClickHouseClient {
	return &ClickHouseClient{
		httpClient:     &http.Client{},
		apiUrl:         apiUrl,
		apiId:          apiId,
		apiKey:         apiKey,
		organizationID: organizationID,
	}
}

type ServiceList struct {
	Services []Service `json:"services"`
}

type Service struct {
	ID             string           `json:"id"`
	Name           string           `json:"name"`
	State          string           `json:"state"`
	Region         string           `json:"region"`
	CloudProvider  string           `json:"cloudProvider"`
	Tier           string           `json:"tier"`
	IdleScaling    map[string]any   `json:"idleScaling"`
	TotalDiskSize  int              `json:"totalDiskSize"`
	TotalMemoryMB  int              `json:"totalMemoryMB"`
	MinTotalMemory int              `json:"minTotalMemory"`
	MaxTotalMemory int              `json:"maxTotalMemory"`
	Created        string           `json:"created"`
	Endpoints      []map[string]any `json:"endpoints"`
}

func (c *ClickHouseClient) GetServices(ctx context.Context) ([]ClickHouseConfigResponse, error) {
	log.Info("Getting services for organization", "organizationID", c.organizationID)
	url := fmt.Sprintf("%s/v1/organizations/%s/services", c.apiUrl, c.organizationID)
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.SetBasicAuth(c.apiId, c.apiKey)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to make request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Error("Unexpected status code", "status", resp.StatusCode)
		body, _ := io.ReadAll(resp.Body)
		log.Error("Response body", "body", string(body))
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	var result ClickHouseListResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return result.Result, nil
}

func NewSyncClickhouseCmd() *cobra.Command {
	var providerName string
	var clickhouseApiUrl string
	var clickhouseApiSecret string
	var clickhouseApiId string
	var organizationID string

	cmd := &cobra.Command{
		Use:   "clickhouse",
		Short: "Sync ClickHouse instances into Ctrlplane",
		Example: heredoc.Doc(`
			$ ctrlc sync clickhouse
		`),
		PreRunE: func(cmd *cobra.Command, args []string) error {
			if clickhouseApiSecret == "" {
				clickhouseApiSecret = os.Getenv("CLICKHOUSE_API_SECRET")
			}
			if clickhouseApiSecret == "" {
				return fmt.Errorf("clickhouse-secret must be provided")
			}
			if organizationID == "" {
				organizationID = os.Getenv("CLICKHOUSE_ORGANIZATION_ID")
			}
			if organizationID == "" {
				return fmt.Errorf("organization-id must be provided")
			}
			if clickhouseApiId == "" {
				clickhouseApiId = os.Getenv("CLICKHOUSE_API_ID")
			}
			if clickhouseApiId == "" {
				return fmt.Errorf("clickhouse-api-id must be provided")
			}
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			log.Info("Syncing ClickHouse instances into Ctrlplane")
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			workspaceId := viper.GetString("workspace")
			ctrlplaneClient, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			chClient := NewClickHouseClient(clickhouseApiUrl, clickhouseApiId, clickhouseApiSecret, organizationID)
			ctx := context.Background()
			services, err := chClient.GetServices(ctx)
			if err != nil {
				return fmt.Errorf("failed to list ClickHouse services: %w", err)
			}

			resources := []api.AgentResource{}
			for _, service := range services {
				var endpoints []string
				for _, endpoint := range service.Endpoints {
					endpointString := fmt.Sprintf("%s://%s:%d", endpoint.Protocol, endpoint.Host, endpoint.Port)
					endpoints = append(endpoints, endpointString)
				}
				connection := service.GetConnection()
				metadata := map[string]string{
					"database/id": service.ID,
					"database/model": "relational",
					"database/port": fmt.Sprintf("%d", connection.Port),
					"database/host": connection.Host,

					"clickhouse/id":                                 service.ID,
					"clickhouse/name":                               service.Name,
					"clickhouse/state":                              service.State,
					"clickhouse/region":                             service.Region,
					"clickhouse/tier":                               service.Tier,
					"clickhouse/endpoints":                          strings.Join(endpoints, ","),
					"clickhouse/data-warehouse-id":                  service.DataWarehouseId,
					"clickhouse/is-primary":                         fmt.Sprintf("%t", service.IsPrimary),
					"clickhouse/is-readonly":                        fmt.Sprintf("%t", service.IsReadonly),
					"clickhouse/release-channel":                    service.ReleaseChannel,
					"clickhouse/encryption-key":                     service.EncryptionKey,
					"clickhouse/encryption-assumed-role-identifier": service.EncryptionAssumedRoleIdentifier,
					"clickhouse/encryption-role-id":                 service.EncryptionRoleId,
					"clickhouse/has-transparent-data-encryption":    fmt.Sprintf("%t", service.HasTransparentDataEncryption),
					"clickhouse/transparent-data-encryption-key-id": service.TransparentDataEncryptionKeyId,
					"clickhouse/iam-role":                           service.IamRole,
					"clickhouse/byoc-id":                            service.ByocId,

					"clickhouse/min-total-memory-gb":   fmt.Sprintf("%d", service.MinTotalMemoryGb),
					"clickhouse/max-total-memory-gb":   fmt.Sprintf("%d", service.MaxTotalMemoryGb),
					"clickhouse/min-replica-memory-gb": fmt.Sprintf("%d", service.MinReplicaMemoryGb),
					"clickhouse/max-replica-memory-gb": fmt.Sprintf("%d", service.MaxReplicaMemoryGb),
					"clickhouse/num-replicas":          fmt.Sprintf("%d", service.NumReplicas),
					"clickhouse/idle-scaling":          fmt.Sprintf("%t", service.IdleScaling),
					"clickhouse/idle-timeout-minutes":  fmt.Sprintf("%d", service.IdleTimeoutMinutes),
				}

				// Create a sanitized name
				name := strings.Split(service.Name, ".")[0]
				resources = append(resources, api.AgentResource{
					Version:    "https://schema.ctrlplane.dev/database/v1",
					Kind:       "ClickhouseCloud",
					Name:       name,
					Identifier: fmt.Sprintf("%s/%s", organizationID, service.ID),
					Config: map[string]any{
						"host": connection.Host,
						"port": connection.Port,
						"username": connection.Username,

						"clickhouse": map[string]any{
							"id":                             service.ID,
							"name":                           service.Name,
							"state":                          service.State,
							"provider":                       service.Provider,
							"region":                         service.Region,
							"endpoints":                      service.Endpoints,
							"iamRole":                        service.IamRole,
							"isPrimary":                      service.IsPrimary,
							"isReadonly":                     service.IsReadonly,
						},
					},
					Metadata: metadata,
				})
			}
			log.Info("Upserting resources", "count", len(resources))
			providerName := fmt.Sprintf("clickhouse-%s", organizationID)
			rp, err := api.NewResourceProvider(ctrlplaneClient, workspaceId, providerName)
			if err != nil {
				return fmt.Errorf("failed to create resource provider: %w", err)
			}
			upsertResp, err := rp.UpsertResource(ctx, resources)
			log.Info("Response from upserting resources", "status", upsertResp.Status)
			if err != nil {
				return fmt.Errorf("failed to upsert resources: %w", err)
			}
			return cliutil.HandleResponseOutput(cmd, upsertResp)
		},
	}

	cmd.Flags().StringVarP(&providerName, "provider", "p", "clickhouse", "The name of the provider to use")
	cmd.Flags().StringVarP(&clickhouseApiUrl, "clickhouse-url", "u", "https://api.clickhouse.cloud", "The URL of the ClickHouse API")
	cmd.Flags().StringVarP(&clickhouseApiSecret, "clickhouse-secret", "s", "", "The API secret to use")
	cmd.Flags().StringVarP(&clickhouseApiId, "clickhouse-api-id", "", "", "The API ID to use")
	cmd.Flags().StringVarP(&organizationID, "organization-id", "o", "", "The ClickHouse organization ID")

	return cmd
}

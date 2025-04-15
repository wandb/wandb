package clickhouse

import (
	"context"
	"encoding/json"
	"fmt"
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

type ClickHouseConfig struct {
	ID             string                   `json:"id"`
	Name           string                   `json:"name"`
	State          string                   `json:"state"`
	Region         string                   `json:"region"`
	CloudProvider  string                   `json:"cloudProvider"`
	Tier           string                   `json:"tier"`
	IdleScaling    map[string]interface{}   `json:"idleScaling"`
	TotalDiskSize  int                      `json:"totalDiskSize"`
	TotalMemoryMB  int                      `json:"totalMemoryMB"`
	MinTotalMemory int                      `json:"minTotalMemory"`
	MaxTotalMemory int                      `json:"maxTotalMemory"`
	Created        string                   `json:"created"`
	Endpoints      []map[string]interface{} `json:"endpoints"`
}

func (c *ClickHouseConfig) Struct() map[string]interface{} {
	b, _ := json.Marshal(c)
	var m map[string]interface{}
	json.Unmarshal(b, &m)
	return m
}

type ClickHouseClient struct {
	httpClient     *http.Client
	apiUrl         string
	apiKey         string
	organizationID string
}

func NewClickHouseClient(apiUrl, apiKey, organizationID string) *ClickHouseClient {
	return &ClickHouseClient{
		httpClient:     &http.Client{},
		apiUrl:         apiUrl,
		apiKey:         apiKey,
		organizationID: organizationID,
	}
}

type ServiceList struct {
	Services []Service `json:"services"`
}

type Service struct {
	ID             string                   `json:"id"`
	Name           string                   `json:"name"`
	State          string                   `json:"state"`
	Region         string                   `json:"region"`
	CloudProvider  string                   `json:"cloudProvider"`
	Tier           string                   `json:"tier"`
	IdleScaling    map[string]interface{}   `json:"idleScaling"`
	TotalDiskSize  int                      `json:"totalDiskSize"`
	TotalMemoryMB  int                      `json:"totalMemoryMB"`
	MinTotalMemory int                      `json:"minTotalMemory"`
	MaxTotalMemory int                      `json:"maxTotalMemory"`
	Created        string                   `json:"created"`
	Endpoints      []map[string]interface{} `json:"endpoints"`
}

func (c *ClickHouseClient) GetServices(ctx context.Context) ([]Service, error) {
	url := fmt.Sprintf("%s/v1/organizations/%s/services", c.apiUrl, c.organizationID)
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", c.apiKey))
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to make request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	var result ServiceList
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return result.Services, nil
}

func NewSyncClickhouseCmd() *cobra.Command {
	var providerName string
	var clickhouseApiUrl string
	var clickhouseApiKey string
	var organizationID string

	cmd := &cobra.Command{
		Use:   "clickhouse",
		Short: "Sync ClickHouse instances into Ctrlplane",
		Example: heredoc.Doc(`
				$ ctrlc sync clickhouse --workspace 2a7c5560-75c9-4dbe-be74-04ee33bf8188
			`),
		PreRunE: func(cmd *cobra.Command, args []string) error {
			if clickhouseApiKey == "" {
				return fmt.Errorf("clickhouse-key must be provided")
			}
			if organizationID == "" {
				return fmt.Errorf("organization-id must be provided")
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
			chClient := NewClickHouseClient(clickhouseApiUrl, clickhouseApiKey, organizationID)
			ctx := context.Background()
			services, err := chClient.GetServices(ctx)
			if err != nil {
				return fmt.Errorf("failed to list ClickHouse services: %w", err)
			}
			resources := []api.AgentResource{}
			for _, service := range services {
				metadata := map[string]string{}
				metadata["clickhouse/id"] = service.ID
				metadata["clickhouse/name"] = service.Name
				metadata["clickhouse/state"] = service.State
				metadata["clickhouse/region"] = service.Region
				metadata["clickhouse/cloud-provider"] = service.CloudProvider
				metadata["clickhouse/tier"] = service.Tier
				metadata["clickhouse/created"] = service.Created

				config := ClickHouseConfig(service) // Direct type conversion since fields match

				// Create a sanitized name
				name := strings.Split(service.Name, ".")[0]
				resources = append(resources, api.AgentResource{
					Version:    "clickhouse/v1",
					Kind:       "Service",
					Name:       name,
					Identifier: fmt.Sprintf("%s/%s", organizationID, service.ID),
					Config:     config.Struct(),
					Metadata:   metadata,
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
	cmd.Flags().StringVarP(&clickhouseApiKey, "clickhouse-key", "k", os.Getenv("CLICKHOUSE_API_KEY"), "The API key to use")
	cmd.Flags().StringVarP(&organizationID, "organization-id", "o", os.Getenv("CLICKHOUSE_ORGANIZATION_ID"), "The ClickHouse organization ID")

	cmd.MarkFlagRequired("organization-id")

	return cmd
}

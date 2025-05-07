package apply

import (
	"context"
	"fmt"

	"path/filepath"

	"os"

	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/google/uuid"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"

	"gopkg.in/yaml.v3"
)

// Config represents the structure of the YAML file
type Config struct {
	Systems map[string]System `yaml:"systems"`
}

type System struct {
	Name        string                `yaml:"name"`
	Description string                `yaml:"description"`
	Deployments map[string]Deployment `yaml:"deployments"`
}

type Deployment struct {
	Name        string            `yaml:"name"`
	Description string            `yaml:"description"`
	SystemName  string            `yaml:"systemName"`
	Metadata    map[string]string `yaml:"metadata"`
}

// NewApplyCommand creates a new apply command
func NewApplyCmd() *cobra.Command {
	var filePath string

	cmd := &cobra.Command{
		Use:   "apply",
		Short: "Apply a YAML configuration file to create systems and deployments",
		Long:  `Apply a YAML configuration file to create systems and deployments in Ctrlplane`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return runApply(filePath)
		},
	}

	cmd.Flags().StringVarP(&filePath, "file", "f", "", "Path to the YAML configuration file (required)")
	cmd.MarkFlagRequired("file")

	return cmd
}

func runApply(filePath string) error {
	ctx := context.Background()
	logger := log.FromContext(ctx)

	// Read and parse the YAML file
	config, err := readConfigFile(filePath)
	if err != nil {
		return fmt.Errorf("failed to read config file: %w", err)
	}

	// Create API client
	apiURL := viper.GetString("url")
	apiKey := viper.GetString("api-key")
	workspace := viper.GetString("workspace")

	workspaceID, err := uuid.Parse(workspace)
	if err != nil {
		return fmt.Errorf("invalid workspace ID: %w", err)
	}

	client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
	if err != nil {
		return fmt.Errorf("failed to create API client: %w", err)
	}

	for slug, system := range config.Systems {
		logger.Info("Upserting system", "name", system.Name)

		systemID, err := upsertSystem(ctx, client, workspaceID, slug, system)
		if err != nil {
			logger.Error("Failed to upsert system", "name", system.Name, "error", err)
			continue
		}
		logger.Info("System created successfully", "name", system.Name, "id", systemID)

		systemIDUUID, err := uuid.Parse(systemID)
		if err != nil {
			return fmt.Errorf("invalid system ID: %w", err)
		}

		for deploymentSlug, deployment := range system.Deployments {
			logger.Info("Creating deployment", "name", deployment.Name)
			_, err := upsertDeployment(ctx, client, systemIDUUID, deploymentSlug, deployment)
			if err != nil {
				logger.Error("Failed to create deployment", "name", deployment.Name, "error", err)
			}
		}
	}

	return nil
}

func readConfigFile(filePath string) (*Config, error) {
	// Resolve absolute path
	absPath, err := filepath.Abs(filePath)
	if err != nil {
		return nil, fmt.Errorf("failed to resolve file path: %w", err)
	}

	// Read file
	data, err := os.ReadFile(absPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read file: %w", err)
	}

	// Parse YAML
	var config Config
	if err := yaml.Unmarshal(data, &config); err != nil {
		return nil, fmt.Errorf("failed to parse YAML: %w", err)
	}

	return &config, nil
}

func upsertSystem(
	ctx context.Context,
	client *api.ClientWithResponses,
	workspaceID uuid.UUID,
	slug string,
	system System,
) (string, error) {
	resp, err := client.CreateSystemWithResponse(ctx, api.CreateSystemJSONRequestBody{
		Slug:        slug,
		WorkspaceId: workspaceID,
		Name:        system.Name,
		Description: &system.Description,
	})

	if err != nil {
		return "", fmt.Errorf("API request failed: %w", err)
	}

	if resp.StatusCode() >= 400 {
		return "", fmt.Errorf("API returned error status: %d", resp.StatusCode())
	}

	if resp.JSON200 != nil {
		return resp.JSON200.Id.String(), nil
	}

	if resp.JSON201 != nil {
		return resp.JSON201.Id.String(), nil
	}

	return "", fmt.Errorf("unexpected response format")
}

func upsertDeployment(
	ctx context.Context,
	client *api.ClientWithResponses,
	systemID uuid.UUID,
	deploymentSlug string,
	deployment Deployment,
) (string, error) {
	resp, err := client.CreateDeploymentWithResponse(ctx, api.CreateDeploymentJSONRequestBody{
		SystemId:    systemID,
		Slug:        deploymentSlug,
		Name:        deployment.Name,
		Description: &deployment.Description,
	})

	if err != nil {
		return "", fmt.Errorf("API request failed: %w", err)
	}
	
	if resp.StatusCode() >= 400 {
		return "", fmt.Errorf("API returned error status: %d", resp.StatusCode())
	}

	if resp.JSON200 != nil {
		return resp.JSON200.Id.String(), nil
	}

	if resp.JSON201 != nil {
		return resp.JSON201.Id.String(), nil
	}

	return "", fmt.Errorf("unexpected response format")
}

package apply

import (
	"context"
	"fmt"
	"sync"

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
	Systems   []System `yaml:"systems"`
	Providers ResourceProvider  `yaml:"resourceProvider"`
}

type System struct {
	Slug         string        `yaml:"slug"`
	Name         string        `yaml:"name"`
	Description  string        `yaml:"description"`
	Deployments  []Deployment  `yaml:"deployments"`
	Environments []Environment `yaml:"environments"`
}

type Environment struct {
	Name             string         `yaml:"name"`
	Description      string         `yaml:"description"`
	ResourceSelector map[string]any `yaml:"resourceSelector"`
}

type Deployment struct {
	Slug        string    `yaml:"slug"`
	Name        string    `yaml:"name"`
	Description *string   `yaml:"description"`
	JobAgent    *JobAgent `yaml:"jobAgent,omitempty"`
}

type JobAgent struct {
	Id     string         `yaml:"id"`
	Config map[string]any `yaml:"config"`
}

type ResourceProvider struct {
	Name      string     `yaml:"name"`
	Resources []Resource `yaml:"resources"`
}

type Resource struct {
	Identifer string            `yaml:"identifer"`
	Name      string            `yaml:"name"`
	Version   string            `yaml:"version"`
	Kind      string            `yaml:"kind"`
	Config    map[string]any    `yaml:"config"`
	Metadata  map[string]string `yaml:"metadata"`
	Variables map[string]any    `yaml:"variables"`
}

// NewApplyCmd creates a new apply command
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

	// Read and parse the YAML file
	config, err := readConfigFile(filePath)
	if err != nil {
		return fmt.Errorf("failed to read config file: %w", err)
	}

	// Create API client
	client, workspaceID, err := createAPIClient()
	if err != nil {
		return err
	}

	// Process systems and collect errors
	processAllSystems(ctx, client, workspaceID, config.Systems)
	processResourceProvider(ctx, client, workspaceID.String(), config.Providers)

	return nil
}

func processResourceProvider(ctx context.Context, client *api.ClientWithResponses, workspaceID string, provider ResourceProvider) {
	if provider.Name == "" {
		log.Info("Resource provider not provided, skipping")
		return
	}

	rp, err := api.NewResourceProvider(client, workspaceID, provider.Name)
	if err != nil {
		log.Error("Failed to create resource provider", "name", provider.Name, "error", err)
		return
	}

	resources := make([]api.AgentResource, 0)
	for _, resource := range provider.Resources {
		resources = append(resources, api.AgentResource{
			Identifier: resource.Identifer,
			Name:       resource.Name,
			Version:    resource.Version,
			Kind:       resource.Kind,
			Config:     resource.Config,
			Metadata:   resource.Metadata,
		})
	}

	upsertResp, err := rp.UpsertResource(ctx, resources)
	if err != nil {
		log.Error("Failed to upsert resources", "name", provider.Name, "error", err)
		return
	}

	log.Info("Response from upserting resources", "status", upsertResp.Status)
}

func createAPIClient() (*api.ClientWithResponses, uuid.UUID, error) {
	apiURL := viper.GetString("url")
	apiKey := viper.GetString("api-key")
	workspace := viper.GetString("workspace")

	workspaceID, err := uuid.Parse(workspace)
	if err != nil {
		return nil, uuid.Nil, fmt.Errorf("invalid workspace ID: %w", err)
	}

	client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
	if err != nil {
		return nil, uuid.Nil, fmt.Errorf("failed to create API client: %w", err)
	}

	return client, workspaceID, nil
}

func processAllSystems(
	ctx context.Context,
	client *api.ClientWithResponses,
	workspaceID uuid.UUID,
	systems []System,
) {
	var systemWg sync.WaitGroup

	for _, system := range systems {
		systemWg.Add(1)
		go processSystem(
			ctx,
			client,
			workspaceID,
			system,
			&systemWg,
		)
	}

	systemWg.Wait()
}

func processSystem(
	ctx context.Context,
	client *api.ClientWithResponses,
	workspaceID uuid.UUID,
	system System,
	systemWg *sync.WaitGroup,
) {
	defer systemWg.Done()

	log.Info("Upserting system", "name", system.Name)
	systemID, err := upsertSystem(ctx, client, workspaceID, system)
	if err != nil {
		log.Error("Failed to upsert system", "name", system.Name, "error", err)
		return
	}
	log.Info("System created successfully", "name", system.Name, "id", systemID)

	systemIDUUID, err := uuid.Parse(systemID)
	if err != nil {
		log.Error("Failed to parse system ID as UUID", "id", systemID, "error", err)
		return
	}

	processSystemDeployments(ctx, client, systemIDUUID, system)
}

func processSystemDeployments(
	ctx context.Context,
	client *api.ClientWithResponses,
	systemID uuid.UUID,
	system System,
) {
	var deploymentWg sync.WaitGroup
	for _, deployment := range system.Deployments {
		deploymentWg.Add(1)
		log.Info("Creating deployment", "system", system.Name, "name", deployment.Name)
		go processDeployment(
			ctx,
			client,
			systemID,
			deployment,
			&deploymentWg,
		)
	}
	deploymentWg.Wait()
}

func processDeployment(
	ctx context.Context,
	client *api.ClientWithResponses,
	systemID uuid.UUID,
	deployment Deployment,
	deploymentWg *sync.WaitGroup,
) {
	defer deploymentWg.Done()

	body := createDeploymentRequestBody(systemID, deployment)

	if deployment.JobAgent != nil {
		jobAgentUUID, err := uuid.Parse(deployment.JobAgent.Id)
		if err != nil {
			log.Error("Failed to parse job agent ID as UUID", "id", deployment.JobAgent.Id, "error", err)
			return
		}
		body.JobAgentId = &jobAgentUUID
		body.JobAgentConfig = &deployment.JobAgent.Config
	}

	_, err := upsertDeployment(ctx, client, body)
	if err != nil {
		log.Error("Failed to create deployment", "name", deployment.Name, "error", err)
	}
}

func createDeploymentRequestBody(systemID uuid.UUID, deployment Deployment) api.CreateDeploymentJSONBody {
	return api.CreateDeploymentJSONBody{
		SystemId:    systemID,
		Slug:        deployment.Slug,
		Name:        deployment.Name,
		Description: deployment.Description,
	}
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
	system System,
) (string, error) {
	resp, err := client.CreateSystemWithResponse(ctx, api.CreateSystemJSONRequestBody{
		WorkspaceId: workspaceID,
		Name:        system.Name,
		Slug:        system.Slug,
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
	deployment api.CreateDeploymentJSONBody,
) (string, error) {
	resp, err := client.CreateDeploymentWithResponse(ctx, api.CreateDeploymentJSONRequestBody(deployment))

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

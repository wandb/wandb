package redis

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
	"google.golang.org/api/redis/v1"
)

// NewSyncRedisCmd creates a new cobra command for syncing Redis instances
func NewSyncRedisCmd() *cobra.Command {
	var project string
	var name string

	cmd := &cobra.Command{
		Use:   "redis",
		Short: "Sync Google Memorystore Redis instances into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Google Cloud credentials are configured via environment variables or application default credentials
			
			# Sync all Redis instances from a project
			$ ctrlc sync google-cloud redis --project my-project
		`),
		PreRunE: validateFlags(&project),
		RunE:    runSync(&project, &name),
	}

	// Add command flags
	cmd.Flags().StringVarP(&name, "provider", "p", "", "Name of the resource provider")
	cmd.Flags().StringVarP(&project, "project", "c", "", "Google Cloud Project ID")
	cmd.MarkFlagRequired("project")

	return cmd
}

// validateFlags ensures required flags are set
func validateFlags(project *string) func(cmd *cobra.Command, args []string) error {
	return func(cmd *cobra.Command, args []string) error {
		if *project == "" {
			return fmt.Errorf("project is required")
		}
		return nil
	}
}

// runSync contains the main sync logic
func runSync(project, name *string) func(cmd *cobra.Command, args []string) error {
	return func(cmd *cobra.Command, args []string) error {
		log.Info("Syncing Redis instances into Ctrlplane", "project", *project)

		ctx := context.Background()

		// Initialize clients
		redisClient, err := initRedisClient(ctx)
		if err != nil {
			return err
		}

		// List and process instances
		resources, err := processInstances(ctx, redisClient, *project)
		if err != nil {
			return err
		}

		// Upsert resources to Ctrlplane
		return upsertToCtrlplane(ctx, resources, project, name)
	}
}

// initRedisClient creates a new Redis Admin client
func initRedisClient(ctx context.Context) (*redis.Service, error) {
	redisClient, err := redis.NewService(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create Redis Admin client: %w", err)
	}
	return redisClient, nil
}

// processInstances lists and processes all Redis instances
func processInstances(ctx context.Context, redisClient *redis.Service, project string) ([]api.AgentResource, error) {
	parent := fmt.Sprintf("projects/%s/locations/-", project)
	instances, err := redisClient.Projects.Locations.Instances.List(parent).Do()
	if err != nil {
		return nil, fmt.Errorf("failed to list Redis instances: %w", err)
	}

	log.Info("Found Redis instances", "count", len(instances.Instances))

	resources := []api.AgentResource{}
	for _, instance := range instances.Instances {
		resource, err := processInstance(ctx, instance, project)
		if err != nil {
			log.Error("Failed to process Redis instance", "name", instance.Name, "error", err)
			continue
		}
		resources = append(resources, resource)
	}

	return resources, nil
}

// processInstance handles processing of a single Redis instance
func processInstance(_ context.Context, instance *redis.Instance, project string) (api.AgentResource, error) {
	metadata := initInstanceMetadata(instance, project)

	// Extract location from name (e.g. projects/myproject/locations/us-central1/instances/myinstance -> us-central1)
	nameParts := strings.Split(instance.Name, "/")
	location := ""
	if len(nameParts) >= 4 {
		location = nameParts[3]
	}

	// Build console URL and instance identifier
	instanceName := getInstanceName(instance.Name)
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/memorystore/redis/locations/%s/instances/%s/details?project=%s",
		location, instanceName, project)
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)

	return api.AgentResource{
		Version:    "ctrlplane.dev/database/v1",
		Kind:       "GoogleRedis",
		Name:       instanceName,
		Identifier: instance.Name,
		Config: map[string]any{
			"name": instanceName,
			"host": instance.Host,
			"port": instance.Port,
			"googleRedis": map[string]any{
				"project":               project,
				"location":              location,
				"version":               instance.RedisVersion,
				"tier":                  instance.Tier,
				"transitEncryptionMode": instance.TransitEncryptionMode,
				"connectMode":           instance.ConnectMode,
			},
		},
		Metadata: metadata,
	}, nil
}

// initInstanceMetadata initializes the base metadata for an instance
func initInstanceMetadata(instance *redis.Instance, project string) map[string]string {
	// Extract location from name
	nameParts := strings.Split(instance.Name, "/")
	location := ""
	instanceName := ""
	if len(nameParts) >= 4 {
		location = nameParts[3]
		if len(nameParts) >= 6 {
			instanceName = nameParts[5]
		}
	}

	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/memorystore/redis/locations/%s/instances/%s/details?project=%s",
		location, instanceName, project)

	metadata := map[string]string{
		"database/type":           "redis",
		"database/host":           instance.Host,
		"database/port":           strconv.FormatInt(instance.Port, 10),
		"database/version":        instance.RedisVersion,
		"database/region":         location,
		"database/tier":           instance.Tier,
		"database/state":          strings.ToLower(instance.State),
		"database/memory-size-gb": strconv.FormatInt(instance.MemorySizeGb, 10),

		"google/project":        project,
		"google/instance-type":  "redis",
		"google/location":       location,
		"google/state":          strings.ToLower(instance.State),
		"google/version":        instance.RedisVersion,
		"google/tier":           instance.Tier,
		"google/memory-size-gb": strconv.FormatInt(instance.MemorySizeGb, 10),
		"google/console-url":    consoleUrl,
		"google/connect-mode":   instance.ConnectMode,
	}

	// Add read replicas info if present
	if instance.ReplicaCount > 0 {
		metadata["database/read-replicas"] = strconv.FormatInt(instance.ReplicaCount, 10)
		metadata["google/redis/read-replicas"] = strconv.FormatInt(instance.ReplicaCount, 10)
	}

	// Add authentication info
	if instance.AuthEnabled {
		metadata["database/auth-enabled"] = "true"
		metadata["security/auth-enabled"] = "true"
	}

	// Add transit encryption info
	if instance.TransitEncryptionMode != "" {
		metadata["database/transit-encryption"] = strings.ToLower(instance.TransitEncryptionMode)
		metadata["security/transit-encryption"] = strings.ToLower(instance.TransitEncryptionMode)
	}

	// Add reserved IP range if present
	if instance.ReservedIpRange != "" {
		metadata["network/reserved-ip-range"] = instance.ReservedIpRange
	}

	// Add maintenance info if present
	if instance.MaintenancePolicy != nil && instance.MaintenancePolicy.WeeklyMaintenanceWindow != nil {
		for i, window := range instance.MaintenancePolicy.WeeklyMaintenanceWindow {
			if window.Day != "" {
				metadata[fmt.Sprintf("google/maintenance/window/%d/day", i)] = window.Day
			}
			if window.StartTime != nil {
				metadata[fmt.Sprintf("google/maintenance/window/%d/start-time", i)] = fmt.Sprintf("%02d:%02d",
					window.StartTime.Hours, window.StartTime.Minutes)
			}
		}
	}

	// Add persistence info if present
	if instance.PersistenceConfig != nil {
		metadata["database/persistence-enabled"] = strconv.FormatBool(instance.PersistenceConfig.PersistenceMode == "RDB")
		if instance.PersistenceConfig.RdbSnapshotPeriod != "" {
			metadata["database/snapshot-period"] = instance.PersistenceConfig.RdbSnapshotPeriod
		}
	}

	return metadata
}

// getInstanceName extracts the instance name from the full resource name
func getInstanceName(fullName string) string {
	parts := strings.Split(fullName, "/")
	if len(parts) >= 6 {
		return parts[5]
	}
	return fullName
}

// upsertToCtrlplane handles upserting resources to Ctrlplane
func upsertToCtrlplane(ctx context.Context, resources []api.AgentResource, project, name *string) error {
	if *name == "" {
		*name = fmt.Sprintf("google-redis-project-%s", *project)
	}

	apiURL := viper.GetString("url")
	apiKey := viper.GetString("api-key")
	workspaceId := viper.GetString("workspace")

	ctrlplaneClient, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
	if err != nil {
		return fmt.Errorf("failed to create API client: %w", err)
	}

	rp, err := api.NewResourceProvider(ctrlplaneClient, workspaceId, *name)
	if err != nil {
		return fmt.Errorf("failed to create resource provider: %w", err)
	}

	upsertResp, err := rp.UpsertResource(ctx, resources)
	if err != nil {
		return fmt.Errorf("failed to upsert resources: %w", err)
	}

	log.Info("Response from upserting resources", "status", upsertResp.Status)
	return nil
}

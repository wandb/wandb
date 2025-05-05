package bigtable

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/kinds"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
	"google.golang.org/api/bigtableadmin/v2"
)

// BigtableInstance represents a Google Cloud Bigtable instance
type BigtableInstance struct {
	ID               string           `json:"id"`
	Name             string           `json:"name"`
	ConnectionMethod ConnectionMethod `json:"connectionMethod"`
}

// ConnectionMethod contains connection details for a Bigtable instance
type ConnectionMethod struct {
	Type     string `json:"type"`
	Project  string `json:"project"`
	Instance string `json:"instance"`
}

// NewSyncBigtableCmd creates a new cobra command for syncing Bigtable instances
func NewSyncBigtableCmd() *cobra.Command {
	var project string
	var name string

	cmd := &cobra.Command{
		Use:   "bigtable",
		Short: "Sync Google Bigtable instances into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Google Cloud credentials are configured via environment variables or application default credentials
			
			# Sync all Bigtable instances from a project
			$ ctrlc sync google-cloud bigtable --project my-project
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
		log.Info("Syncing Bigtable instances into Ctrlplane", "project", *project)

		ctx := context.Background()

		// Initialize clients
		adminClient, err := initBigtableClient(ctx)
		if err != nil {
			return err
		}

		// List and process instances
		resources, err := processInstances(ctx, adminClient, *project)
		if err != nil {
			return err
		}

		// Upsert resources to Ctrlplane
		return upsertToCtrlplane(ctx, resources, project, name)
	}
}

// initBigtableClient creates a new Bigtable Admin client
func initBigtableClient(ctx context.Context) (*bigtableadmin.Service, error) {
	adminClient, err := bigtableadmin.NewService(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create Bigtable Admin client: %w", err)
	}
	return adminClient, nil
}

// processInstances lists and processes all Bigtable instances
func processInstances(ctx context.Context, adminClient *bigtableadmin.Service, project string) ([]api.AgentResource, error) {
	projectParent := fmt.Sprintf("projects/%s", project)
	instances, err := adminClient.Projects.Instances.List(projectParent).Do()
	if err != nil {
		return nil, fmt.Errorf("failed to list instances: %w", err)
	}

	log.Info("Found instances", "count", len(instances.Instances))

	resources := []api.AgentResource{}
	for _, instance := range instances.Instances {
		resource, err := processInstance(ctx, adminClient, instance, project)
		if err != nil {
			log.Error("Failed to process instance", "name", instance.Name, "error", err)
			continue
		}
		resources = append(resources, resource)
	}

	return resources, nil
}

// processInstance handles processing of a single Bigtable instance
func processInstance(_ context.Context, adminClient *bigtableadmin.Service, instance *bigtableadmin.Instance, project string) (api.AgentResource, error) {
	metadata := initInstanceMetadata(instance, project)

	// Process clusters
	locations, err := processClusters(adminClient, instance, metadata)
	if err != nil {
		log.Error("Error processing clusters", "error", err)
	}
	sort.Strings(locations)
	metadata["google/locations"] = strings.Join(locations, ",")

	// Process tables
	if err := processTables(adminClient, instance, metadata); err != nil {
		log.Error("Error processing tables", "error", err)
	}

	// Build console URL and instance identifier
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/bigtable/instances/%s/overview?project=%s",
		instance.Name, project)
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)
	instanceFullName := fmt.Sprintf("projects/%s/instances/%s", project, instance.Name)

	return api.AgentResource{
		Version:    "ctrlplane.dev/database/v1",
		Kind:       "GoogleBigtable",
		Name:       instance.DisplayName,
		Identifier: instanceFullName,
		Config: map[string]any{
			"name": instance.Name,
			"host": instance.Name,
			"port": 443,
			"googleBigtable": map[string]any{
				"project":    project,
				"instanceId": instance.Name,
				"state":      strings.ToLower(instance.State),
				"type":       instance.Type,
			},
		},
		Metadata: metadata,
	}, nil
}

// initInstanceMetadata initializes the base metadata for an instance
func initInstanceMetadata(instance *bigtableadmin.Instance, project string) map[string]string {
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/bigtable/instances/%s/overview?project=%s",
		instance.Name, project)

	// Get Bigtable version Bigtable doesn't have a traditional version number
	// like other databases We'll use the instance type (PRODUCTION or
	// DEVELOPMENT) as a proxy for version and add additional metadata about the
	// instance
	bigtableVersion := "unknown"
	switch instance.Type {
	case "PRODUCTION":
		bigtableVersion = "production"
	case "DEVELOPMENT":
		bigtableVersion = "development"
	default:
		bigtableVersion = strings.ToLower(instance.Type)
	}

	// For version metadata fields, we'll use the instance type Since Bigtable
	// doesn't have semantic versioning, we'll use 1.0.0 for production and
	// 0.1.0 for development instances to maintain compatibility with version
	// fields
	versionMajor, versionMinor, versionPatch := "0", "0", "0"
	if bigtableVersion == "production" {
		versionMajor, versionMinor, versionPatch = "1", "0", "0"
	}
	if bigtableVersion == "development" {
		versionMajor, versionMinor, versionPatch = "0", "1", "0"
	}

	metadata := map[string]string{
		kinds.DBMetadataType:  "bigtable",
		kinds.DBMetadataHost:  instance.Name,
		kinds.DBMetadataName:  instance.Name,
		kinds.DBMetadataPort:  "443",
		kinds.DBMetadataState: strings.ToLower(instance.State),
		kinds.DBMetadataSSL:   "true",

		kinds.DBMetadataVersion:      bigtableVersion,
		kinds.DBMetadataVersionMajor: versionMajor,
		kinds.DBMetadataVersionMinor: versionMinor,
		kinds.DBMetadataVersionPatch: versionPatch,

		"google/project":       project,
		"google/instance-type": "bigtable",
		"google/console-url":   consoleUrl,
		"google/state":         strings.ToLower(instance.State),
		"google/type":          instance.Type,
	}

	for key, value := range instance.Labels {
		metadata[fmt.Sprintf("tags/%s", key)] = value
	}

	return metadata
}

// processClusters handles processing of Bigtable clusters
func processClusters(adminClient *bigtableadmin.Service, instance *bigtableadmin.Instance, metadata map[string]string) ([]string, error) {
	log.Info("Listing clusters", "name", instance.Name)

	clusters, err := adminClient.Projects.Instances.Clusters.List(instance.Name).Do()
	if err != nil {
		return nil, err
	}

	locations := []string{}
	if clusters != nil {
		metadata["google/bigtable/cluster-count"] = strconv.FormatInt(int64(len(clusters.Clusters)), 10)

		for _, cluster := range clusters.Clusters {
			name := strings.ReplaceAll(cluster.Name, instance.Name+"/clusters/", "")
			location := strings.ReplaceAll(cluster.Location, "projects/"+instance.Name+"/locations/", "")

			metadata[fmt.Sprintf("google/bigtable/cluster/%s", name)] = "true"
			metadata[fmt.Sprintf("google/bigtable/cluster/%s/location", name)] = location
			metadata[fmt.Sprintf("google/bigtable/cluster/%s/state", name)] = cluster.State
			metadata[fmt.Sprintf("google/bigtable/cluster/%s/serve-nodes", name)] = strconv.FormatInt(cluster.ServeNodes, 10)

			if !slices.Contains(locations, location) {
				locations = append(locations, location)
			}
		}
	}

	return locations, nil
}

// processTables handles processing of Bigtable tables
func processTables(adminClient *bigtableadmin.Service, instance *bigtableadmin.Instance, metadata map[string]string) error {
	log.Info("Listing tables", "name", instance.Name)

	tables, err := adminClient.Projects.Instances.Tables.List(instance.Name).Do()
	if err != nil {
		return err
	}

	if tables != nil {
		tableNames := []string{}
		totalSizeBytes := int64(0)

		metadata["google/bigtable/table-count"] = strconv.FormatInt(int64(len(tables.Tables)), 10)

		for _, table := range tables.Tables {
			name := strings.ReplaceAll(table.Name, instance.Name+"/tables/", "")
			tableNames = append(tableNames, name)

			metadata[fmt.Sprintf("google/bigtable/table/%s", name)] = "true"

			if table.Stats != nil {
				totalSizeBytes += table.Stats.LogicalDataBytes
				metadata[fmt.Sprintf("google/bigtable/table/%s/row-count", name)] = strconv.FormatInt(table.Stats.RowCount, 10)
				metadata[fmt.Sprintf("google/bigtable/table/%s/size-gb", name)] = strconv.FormatFloat(float64(table.Stats.LogicalDataBytes)/1024/1024/1024, 'f', 2, 64)
			}
		}

		sort.Strings(tableNames)
		metadata["google/bigtable/tables"] = strings.Join(tableNames, ",")
		metadata["database/size-gb"] = strconv.FormatFloat(float64(totalSizeBytes)/1024/1024/1024, 'f', 0, 64)
	}

	return nil
}

// upsertToCtrlplane handles upserting resources to Ctrlplane
func upsertToCtrlplane(ctx context.Context, resources []api.AgentResource, project, name *string) error {
	if *name == "" {
		*name = fmt.Sprintf("google-bigtable-project-%s", *project)
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

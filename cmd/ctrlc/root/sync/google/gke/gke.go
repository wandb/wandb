package gke

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/Masterminds/semver"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/kinds"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
	"google.golang.org/api/container/v1"
)

// NewSyncGKECmd creates a new cobra command for syncing GKE clusters
func NewSyncGKECmd() *cobra.Command {
	var project string
	var name string

	cmd := &cobra.Command{
		Use:   "gke",
		Short: "Sync Google Kubernetes Engine clusters into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Google Cloud credentials are configured via environment variables or application default credentials
			
			# Sync all GKE clusters from a project
			$ ctrlc sync google-cloud gke --project my-project
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
		log.Info("Syncing GKE clusters into Ctrlplane", "project", *project)

		ctx := context.Background()

		// Initialize clients
		gkeClient, err := initGKEClient(ctx)
		if err != nil {
			return err
		}

		// List and process clusters
		resources, err := processClusters(ctx, gkeClient, *project)
		if err != nil {
			return err
		}

		// Upsert resources to Ctrlplane
		return upsertToCtrlplane(ctx, resources, project, name)
	}
}

// initGKEClient creates a new GKE client
func initGKEClient(ctx context.Context) (*container.Service, error) {
	gkeClient, err := container.NewService(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create GKE client: %w", err)
	}
	return gkeClient, nil
}

// processClusters lists and processes all GKE clusters
func processClusters(ctx context.Context, gkeClient *container.Service, project string) ([]api.AgentResource, error) {
	parent := fmt.Sprintf("projects/%s/locations/-", project)
	resp, err := gkeClient.Projects.Locations.Clusters.List(parent).Do()
	if err != nil {
		return nil, fmt.Errorf("failed to list GKE clusters: %w", err)
	}

	log.Info("Found GKE clusters", "count", len(resp.Clusters))

	resources := []api.AgentResource{}
	for _, cluster := range resp.Clusters {
		resource, err := processCluster(ctx, cluster, project)
		if err != nil {
			log.Error("Failed to process GKE cluster", "name", cluster.Name, "error", err)
			continue
		}
		resources = append(resources, resource)
	}

	return resources, nil
}

// processCluster handles processing of a single GKE cluster
func processCluster(_ context.Context, cluster *container.Cluster, project string) (api.AgentResource, error) {
	metadata := initClusterMetadata(cluster, project)

	// Extract location info
	isRegional := strings.Contains(cluster.Location, "-")
	locationType := "zone"
	if isRegional {
		locationType = "region"
	}

	// Calculate total node count across all node pools
	totalNodeCount := 0
	for _, nodePool := range cluster.NodePools {
		if nodePool.Autoscaling != nil && nodePool.Autoscaling.Enabled {
			totalNodeCount += int(nodePool.InitialNodeCount)
		}
	}

	// Build console URL
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/kubernetes/clusters/details/%s/%s?project=%s",
		cluster.Location, cluster.Name, project)
	metadata[kinds.CtrlplaneMetadataLinks] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)

	certificateAuthorityData := ""
	if cluster.MasterAuth != nil && cluster.MasterAuth.ClusterCaCertificate != "" {
		certificateAuthorityData = cluster.MasterAuth.ClusterCaCertificate
	}
	return api.AgentResource{
		Version:    "ctrlplane.dev/kubernetes/cluster/v1",
		Kind:       "GoogleKubernetesEngine",
		Name:       cluster.Name,
		Identifier: cluster.SelfLink,
		Config: map[string]any{
			"name":    cluster.Name,
			"version": cluster.CurrentMasterVersion,
			"server": map[string]any{
				"endpoint":                 cluster.Endpoint,
				"certificateAuthorityData": certificateAuthorityData,
			},

			// Provider-specific implementation details
			"googleKubernetesEngine": map[string]any{
				"project":       project,
				"location":      cluster.Location,
				"locationType":  locationType,
				"networkPolicy": cluster.NetworkPolicy != nil && cluster.NetworkPolicy.Enabled,
				"autopilot":     cluster.Autopilot != nil && cluster.Autopilot.Enabled,
				"status":        cluster.Status,
				"network":       getResourceName(cluster.Network),
			},
		},
		Metadata: metadata,
	}, nil
}

// initClusterMetadata initializes the base metadata for a cluster
func initClusterMetadata(cluster *container.Cluster, project string) map[string]string {
	// Extract location type (zone vs region)
	isRegional := strings.Contains(cluster.Location, "-")
	locationType := "zone"
	if isRegional {
		locationType = "region"
	}

	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/kubernetes/clusters/details/%s/%s?project=%s",
		cluster.Location, cluster.Name, project)

	version, err := semver.NewVersion(cluster.CurrentMasterVersion)
	if err != nil {
		log.Error("Failed to parse Kubernetes version", "version", cluster.CurrentMasterVersion, "error", err)
	}

	noramlizedStatus := "unknown"
	switch cluster.Status {
	case "PROVISIONING":
		noramlizedStatus = "creating"
	case "RUNNING":
		noramlizedStatus = "running"
	case "RECONCILING":
		noramlizedStatus = "updating"
	case "DELETING":
		noramlizedStatus = "deleting"
	case "ERROR":
		noramlizedStatus = "failed"
	}

	metadata := map[string]string{
		"network/type": "vpc",
		"network/name": cluster.Network,

		kinds.K8SMetadataType:   "gke",
		kinds.K8SMetadataName:   cluster.Name,
		kinds.K8SMetadataStatus: noramlizedStatus,

		kinds.K8SMetadataVersion:           fmt.Sprintf("%d.%d.%d", version.Major(), version.Minor(), version.Patch()),
		kinds.K8SMetadataVersionMajor:      strconv.FormatUint(uint64(version.Major()), 10),
		kinds.K8SMetadataVersionMinor:      strconv.FormatUint(uint64(version.Minor()), 10),
		kinds.K8SMetadataVersionPatch:      strconv.FormatUint(uint64(version.Patch()), 10),
		kinds.K8SMetadataVersionPrerelease: version.Prerelease(),

		"kubernetes/location":        cluster.Location,
		"kubernetes/location-type":   locationType,
		"kubernetes/endpoint":        cluster.Endpoint,
		"kubernetes/node-pool-count": strconv.Itoa(len(cluster.NodePools)),

		"google/project":       project,
		"google/resource-type": "container.googleapis.com/Cluster",
		"google/location":      cluster.Location,
		"google/location-type": locationType,
		"google/status":        cluster.Status,
		"google/console-url":   consoleUrl,
		"google/self-link":     cluster.SelfLink,
	}

	// Process creation time
	if cluster.CreateTime != "" {
		if t, err := time.Parse(time.RFC3339, cluster.CreateTime); err == nil {
			metadata[kinds.K8SMetadataCreated] = t.Format(time.RFC3339)
		} else {
			metadata[kinds.K8SMetadataCreated] = cluster.CreateTime
		}
	}

	// Process expiration time
	if cluster.ExpireTime != "" {
		if t, err := time.Parse(time.RFC3339, cluster.ExpireTime); err == nil {
			metadata["kubernetes/expires"] = t.Format(time.RFC3339)
		} else {
			metadata["kubernetes/expires"] = cluster.ExpireTime
		}
	}

	// Handle node config
	totalNodeCount := 0
	autoscalingNodePools := 0
	for _, nodePool := range cluster.NodePools {
		metadata[fmt.Sprintf("kubernetes/node-pool/%s/name", nodePool.Name)] = nodePool.Name
		metadata[fmt.Sprintf("kubernetes/node-pool/%s/version", nodePool.Name)] = nodePool.Version
		metadata[fmt.Sprintf("kubernetes/node-pool/%s/status", nodePool.Name)] = nodePool.Status

		if nodePool.Config != nil {
			if nodePool.Config.MachineType != "" {
				metadata[fmt.Sprintf("kubernetes/node-pool/%s/machine-type", nodePool.Name)] = nodePool.Config.MachineType
			}

			if len(nodePool.Config.OauthScopes) > 0 {
				metadata[fmt.Sprintf("kubernetes/node-pool/%s/oauth-scope-count", nodePool.Name)] = strconv.Itoa(len(nodePool.Config.OauthScopes))
			}

			// Disk details
			if nodePool.Config.DiskSizeGb > 0 {
				metadata[fmt.Sprintf("kubernetes/node-pool/%s/disk-size-gb", nodePool.Name)] = strconv.FormatInt(nodePool.Config.DiskSizeGb, 10)
			}
			if nodePool.Config.DiskType != "" {
				metadata[fmt.Sprintf("kubernetes/node-pool/%s/disk-type", nodePool.Name)] = nodePool.Config.DiskType
			}
		}

		// Node count
		if nodePool.Autoscaling != nil && nodePool.Autoscaling.Enabled {
			autoscalingNodePools++
			metadata[fmt.Sprintf("kubernetes/node-pool/%s/autoscaling", nodePool.Name)] = "enabled"
			metadata[fmt.Sprintf("kubernetes/node-pool/%s/min-nodes", nodePool.Name)] = strconv.FormatInt(nodePool.Autoscaling.MinNodeCount, 10)
			metadata[fmt.Sprintf("kubernetes/node-pool/%s/max-nodes", nodePool.Name)] = strconv.FormatInt(nodePool.Autoscaling.MaxNodeCount, 10)
			// For autoscaling pools, use current node count
			totalNodeCount += int(nodePool.InitialNodeCount)
		} else {
			metadata[fmt.Sprintf("kubernetes/node-pool/%s/autoscaling", nodePool.Name)] = "disabled"
			metadata[fmt.Sprintf("kubernetes/node-pool/%s/node-count", nodePool.Name)] = strconv.FormatInt(nodePool.InitialNodeCount, 10)
			// For fixed pools, use configured node count
			totalNodeCount += int(nodePool.InitialNodeCount)
		}
	}
	metadata["kubernetes/autoscaling-node-pool-count"] = strconv.Itoa(autoscalingNodePools)
	metadata["kubernetes/total-node-count"] = strconv.Itoa(totalNodeCount)

	// Networking details
	if cluster.Network != "" {
		metadata["network/vpc"] = getResourceName(cluster.Network)
	}
	if cluster.Subnetwork != "" {
		metadata["network/subnet"] = getResourceName(cluster.Subnetwork)
	}
	if cluster.ClusterIpv4Cidr != "" {
		metadata["network/pod-cidr"] = cluster.ClusterIpv4Cidr
	}
	if cluster.ServicesIpv4Cidr != "" {
		metadata["network/service-cidr"] = cluster.ServicesIpv4Cidr
	}

	// Add-ons status
	if cluster.AddonsConfig != nil {
		if cluster.AddonsConfig.HttpLoadBalancing != nil {
			metadata["kubernetes/addon/http-load-balancing"] =
				strconv.FormatBool(!cluster.AddonsConfig.HttpLoadBalancing.Disabled)
		}
		if cluster.AddonsConfig.HorizontalPodAutoscaling != nil {
			metadata["kubernetes/addon/horizontal-pod-autoscaling"] =
				strconv.FormatBool(!cluster.AddonsConfig.HorizontalPodAutoscaling.Disabled)
		}
		if cluster.AddonsConfig.NetworkPolicyConfig != nil {
			metadata["kubernetes/addon/network-policy"] =
				strconv.FormatBool(!cluster.AddonsConfig.NetworkPolicyConfig.Disabled)
		}
	}

	// Network policy
	if cluster.NetworkPolicy != nil {
		metadata["kubernetes/network-policy"] = strconv.FormatBool(cluster.NetworkPolicy.Enabled)
		if cluster.NetworkPolicy.Provider != "" {
			metadata["kubernetes/network-policy-provider"] = cluster.NetworkPolicy.Provider
		}
	}

	metadata["kubernetes/ip-allocation-policy"] = "false"
	// IP allocation policy
	if cluster.IpAllocationPolicy != nil {
		metadata["kubernetes/ip-allocation-policy"] = "true"
		if cluster.IpAllocationPolicy.UseIpAliases {
			metadata["kubernetes/ip-aliases"] = "true"
		}
	}

	// Maintenance policy
	if cluster.MaintenancePolicy != nil && cluster.MaintenancePolicy.Window != nil {
		if cluster.MaintenancePolicy.Window.DailyMaintenanceWindow != nil {
			window := cluster.MaintenancePolicy.Window.DailyMaintenanceWindow
			metadata["kubernetes/maintenance-window"] = "daily"
			metadata["kubernetes/maintenance-start-time"] = window.StartTime
		} else if cluster.MaintenancePolicy.Window.RecurringWindow != nil {
			window := cluster.MaintenancePolicy.Window.RecurringWindow
			metadata["kubernetes/maintenance-window"] = "recurring"
			metadata["kubernetes/maintenance-recurrence"] = window.Recurrence
		}
	}

	// Autopilot
	if cluster.Autopilot != nil && cluster.Autopilot.Enabled {
		metadata["google/autopilot"] = "true"
	} else {
		metadata["google/autopilot"] = "false"
	}

	// Logging and monitoring
	if cluster.LoggingService != "" {
		metadata["operations/logging"] = cluster.LoggingService
	}
	if cluster.MonitoringService != "" {
		metadata["operations/monitoring"] = cluster.MonitoringService
	}

	for key, value := range cluster.ResourceLabels {
		metadata[fmt.Sprintf("tags/%s", key)] = value
	}

	return metadata
}

// getResourceName extracts the resource name from its full path
func getResourceName(fullPath string) string {
	if fullPath == "" {
		return ""
	}
	parts := strings.Split(fullPath, "/")
	return parts[len(parts)-1]
}

var relationshipRules = []api.CreateResourceRelationshipRule{
	{
		Reference:      "network",
		Name:           "Google Cloud Cluster Network",
		DependencyType: api.ProvisionedIn,

		SourceKind:    "GoogleKubernetesEngine",
		SourceVersion: "ctrlplane.dev/kubernetes/cluster/v1",

		TargetKind:    "GoogleNetwork",
		TargetVersion: "ctrlplane.dev/network/v1",

		MetadataKeysMatch: &[]string{"google/project", "network/name"},
	},
}

// upsertToCtrlplane handles upserting resources to Ctrlplane
func upsertToCtrlplane(ctx context.Context, resources []api.AgentResource, project, name *string) error {
	if *name == "" {
		*name = fmt.Sprintf("google-gke-project-%s", *project)
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

	err = rp.AddResourceRelationshipRule(ctx, relationshipRules)
	if err != nil {
		log.Error("Failed to add resource relationship rule", "name", *name, "error", err)
	}

	upsertResp, err := rp.UpsertResource(ctx, resources)
	if err != nil {
		return fmt.Errorf("failed to upsert resources: %w", err)
	}

	log.Info("Response from upserting resources", "status", upsertResp.Status)
	return nil
}

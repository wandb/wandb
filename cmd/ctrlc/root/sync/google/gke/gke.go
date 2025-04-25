package gke

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
	"google.golang.org/api/container/v1"
)

// GKECluster represents a Google Kubernetes Engine cluster
type GKECluster struct {
	Name        string `json:"name"`
	Location    string `json:"location"`
	NodeCount   int    `json:"nodeCount"`
	K8sVersion  string `json:"k8sVersion"`
}

// NewSyncGKECmd creates a new cobra command for syncing GKE clusters
func NewSyncGKECmd() *cobra.Command {
	var project string
	var name string

	cmd := &cobra.Command{
		Use:   "google-gke",
		Short: "Sync Google Kubernetes Engine clusters into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Google Cloud credentials are configured via environment variables or application default credentials
			
			# Sync all GKE clusters from a project
			$ ctrlc sync google-gke --project my-project
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
		resource, err := processCluster(ctx, gkeClient, cluster, project)
		if err != nil {
			log.Error("Failed to process GKE cluster", "name", cluster.Name, "error", err)
			continue
		}
		resources = append(resources, resource)
	}

	return resources, nil
}

// processCluster handles processing of a single GKE cluster
func processCluster(_ context.Context, gkeClient *container.Service, cluster *container.Cluster, project string) (api.AgentResource, error) {
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
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)

	certificateAuthorityData := ""
	if cluster.MasterAuth != nil && cluster.MasterAuth.ClusterCaCertificate != "" {
		certificateAuthorityData = cluster.MasterAuth.ClusterCaCertificate
	}
	return api.AgentResource{
		Version:    "ctrlplane.dev/kubernetes/cluster/v1",
		Kind:       "GoogleGKE",
		Name:       cluster.Name,
		Identifier: cluster.SelfLink,
		Config: map[string]any{
			"name": cluster.Name,
			"version": cluster.CurrentMasterVersion,
			"server": map[string]any{
				"endpoint": cluster.Endpoint,
				"certificateAuthorityData": certificateAuthorityData,
			},
			"googleKubernetesEngine": map[string]any{
				"project":           project,
				"location":          cluster.Location,
				"locationType":      locationType,
				"networkPolicy":     cluster.NetworkPolicy != nil && cluster.NetworkPolicy.Enabled,
				"autopilot":         cluster.Autopilot != nil && cluster.Autopilot.Enabled,
				"status":            cluster.Status,
				"network":           getResourceName(cluster.Network),
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

	metadata := map[string]string{
		"kubernetes/type":            "gke",
		"kubernetes/name":            cluster.Name,
		"kubernetes/k8s-version":     cluster.CurrentMasterVersion,
		"kubernetes/location":        cluster.Location,
		"kubernetes/location-type":   locationType,
		"kubernetes/status":          cluster.Status,
		"kubernetes/endpoint":        cluster.Endpoint,
		"kubernetes/node-pool-count": strconv.Itoa(len(cluster.NodePools)),
		
		"google/project":             project,
		"google/resource-type":       "container.googleapis.com/Cluster",
		"google/location":            cluster.Location,
		"google/location-type":       locationType,
		"google/status":              cluster.Status,
		"google/console-url":         consoleUrl,
		"google/self-link":           cluster.SelfLink,
	}

	// Process creation time
	if cluster.CreateTime != "" {
		if t, err := time.Parse(time.RFC3339, cluster.CreateTime); err == nil {
			metadata["kubernetes/created"] = t.Format(time.RFC3339)
		} else {
			metadata["kubernetes/created"] = cluster.CreateTime
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
	for i, nodePool := range cluster.NodePools {
		metadata[fmt.Sprintf("kubernetes/node-pool/%d/name", i)] = nodePool.Name
		metadata[fmt.Sprintf("kubernetes/node-pool/%d/version", i)] = nodePool.Version
		metadata[fmt.Sprintf("kubernetes/node-pool/%d/status", i)] = nodePool.Status
		
		if nodePool.Config != nil {
			if nodePool.Config.MachineType != "" {
				metadata[fmt.Sprintf("kubernetes/node-pool/%d/machine-type", i)] = nodePool.Config.MachineType
			}
			
			if len(nodePool.Config.OauthScopes) > 0 {
				metadata[fmt.Sprintf("kubernetes/node-pool/%d/oauth-scope-count", i)] = strconv.Itoa(len(nodePool.Config.OauthScopes))
			}
			
			// Disk details
			if nodePool.Config.DiskSizeGb > 0 {
				metadata[fmt.Sprintf("kubernetes/node-pool/%d/disk-size-gb", i)] = strconv.FormatInt(nodePool.Config.DiskSizeGb, 10)
			}
			if nodePool.Config.DiskType != "" {
				metadata[fmt.Sprintf("kubernetes/node-pool/%d/disk-type", i)] = nodePool.Config.DiskType
			}
		}
		
		// Node count
		if nodePool.Autoscaling != nil && nodePool.Autoscaling.Enabled {
			metadata[fmt.Sprintf("kubernetes/node-pool/%d/autoscaling", i)] = "enabled"
			metadata[fmt.Sprintf("kubernetes/node-pool/%d/min-nodes", i)] = strconv.FormatInt(nodePool.Autoscaling.MinNodeCount, 10)
			metadata[fmt.Sprintf("kubernetes/node-pool/%d/max-nodes", i)] = strconv.FormatInt(nodePool.Autoscaling.MaxNodeCount, 10)
			// For autoscaling pools, use current node count
			totalNodeCount += int(nodePool.InitialNodeCount)
		} else {
			metadata[fmt.Sprintf("kubernetes/node-pool/%d/autoscaling", i)] = "disabled"
			metadata[fmt.Sprintf("kubernetes/node-pool/%d/node-count", i)] = strconv.FormatInt(nodePool.InitialNodeCount, 10)
			// For fixed pools, use configured node count
			totalNodeCount += int(nodePool.InitialNodeCount)
		}
	}
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

	upsertResp, err := rp.UpsertResource(ctx, resources)
	if err != nil {
		return fmt.Errorf("failed to upsert resources: %w", err)
	}

	log.Info("Response from upserting resources", "status", upsertResp.Status)
	return nil
}
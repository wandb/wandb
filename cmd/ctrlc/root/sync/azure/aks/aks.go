package aks

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azidentity"
	"github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/containerservice/armcontainerservice"
	"github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/resources/armsubscriptions"
	"github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/subscription/armsubscription"
	"github.com/MakeNowJust/heredoc/v2"
	"github.com/Masterminds/semver"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/kinds"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

// NewSyncAKSCmd creates a new cobra command for syncing AKS clusters
func NewSyncAKSCmd() *cobra.Command {
	var subscriptionID string
	var name string

	cmd := &cobra.Command{
		Use:   "aks",
		Short: "Sync Azure Kubernetes Service clusters into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Azure credentials are configured via environment variables or Azure CLI
			
			# Sync all AKS clusters from the subscription
			$ ctrlc sync azure aks
			
			# Sync all AKS clusters from a specific subscription
			$ ctrlc sync azure aks --subscription-id 00000000-0000-0000-0000-000000000000
			
			# Sync all AKS clusters every 5 minutes
			$ ctrlc sync azure aks --interval 5m
		`),
		RunE: runSync(&subscriptionID, &name),
	}

	cmd.Flags().StringVarP(&name, "provider", "p", "", "Name of the resource provider")
	cmd.Flags().StringVarP(&subscriptionID, "subscription-id", "s", "", "Azure Subscription ID")

	return cmd
}

func runSync(subscriptionID, name *string) func(cmd *cobra.Command, args []string) error {
	return func(cmd *cobra.Command, args []string) error {
		ctx := context.Background()

		// Initialize Azure credential from environment or CLI
		cred, err := azidentity.NewDefaultAzureCredential(nil)
		if err != nil {
			return fmt.Errorf("failed to obtain Azure credential: %w", err)
		}

		// If subscription ID is not provided, get the default one
		if *subscriptionID == "" {
			defaultSubscriptionID, err := getDefaultSubscriptionID(ctx, cred)
			if err != nil {
				return fmt.Errorf("failed to get default subscription ID: %w", err)
			}
			*subscriptionID = defaultSubscriptionID
			log.Info("Using default subscription ID", "subscriptionID", *subscriptionID)
		}

		// Get tenant ID from the subscription
		tenantID, err := getTenantIDFromSubscription(ctx, cred, *subscriptionID)
		if err != nil {
			log.Warn("Failed to get tenant ID from subscription, falling back to environment variables", "error", err)
			tenantID = getTenantIDFromEnv()
		}

		log.Info("Syncing all AKS clusters", "subscriptionID", *subscriptionID, "tenantID", tenantID)

		// Process AKS clusters
		resources, err := processClusters(ctx, cred, *subscriptionID, tenantID)
		if err != nil {
			return err
		}

		if len(resources) == 0 {
			log.Info("No AKS clusters found")
			return nil
		}

		// If name is not provided, use subscription ID
		if *name == "" {
			*name = fmt.Sprintf("azure-aks-%s", *subscriptionID)
		}

		// Upsert resources to Ctrlplane
		return upsertToCtrlplane(ctx, resources, subscriptionID, name)
	}
}

func getTenantIDFromSubscription(ctx context.Context, cred azcore.TokenCredential, subscriptionID string) (string, error) {
	// Create a subscriptions client
	subsClient, err := armsubscriptions.NewClient(cred, nil)
	if err != nil {
		return "", fmt.Errorf("failed to create subscriptions client: %w", err)
	}

	// Get the subscription details
	resp, err := subsClient.Get(ctx, subscriptionID, nil)
	if err != nil {
		return "", fmt.Errorf("failed to get subscription details: %w", err)
	}

	// Extract tenant ID from subscription
	if resp.TenantID == nil || *resp.TenantID == "" {
		return "", fmt.Errorf("subscription doesn't have a tenant ID")
	}

	return *resp.TenantID, nil
}

func getTenantIDFromEnv() string {
	// Check environment variables
	if tenantID := os.Getenv("AZURE_TENANT_ID"); tenantID != "" {
		return tenantID
	}
	
	// Check viper config
	if tenantID := viper.GetString("azure.tenant-id"); tenantID != "" {
		return tenantID
	}
	
	return ""
}

func getDefaultSubscriptionID(ctx context.Context, cred azcore.TokenCredential) (string, error) {
	subClient, err := armsubscription.NewSubscriptionsClient(cred, nil)
	if err != nil {
		return "", fmt.Errorf("failed to create subscription client: %w", err)
	}

	pager := subClient.NewListPager(nil)
	for pager.More() {
		page, err := pager.NextPage(ctx)
		if err != nil {
			return "", fmt.Errorf("failed to list subscriptions: %w", err)
		}

		// Return the first subscription as default
		if len(page.Value) > 0 && page.Value[0].SubscriptionID != nil {
			return *page.Value[0].SubscriptionID, nil
		}
	}

	return "", fmt.Errorf("no subscriptions found")
}

func processClusters(ctx context.Context, cred azcore.TokenCredential, subscriptionID string, tenantID string) ([]api.AgentResource, error) {
	var resources []api.AgentResource
	var mu sync.Mutex
	var wg sync.WaitGroup
	var syncErrors []error

	// Create AKS client
	aksClient, err := armcontainerservice.NewManagedClustersClient(subscriptionID, cred, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create AKS client: %w", err)
	}

	// List all clusters in the subscription
	pager := aksClient.NewListPager(nil)
	for pager.More() {
		page, err := pager.NextPage(ctx)
		if err != nil {
			return nil, fmt.Errorf("failed to list AKS clusters: %w", err)
		}

		for _, cluster := range page.Value {
			wg.Add(1)
			go func(mc *armcontainerservice.ManagedCluster) {
				defer wg.Done()

				resource, err := processCluster(ctx, mc, subscriptionID, tenantID)
				if err != nil {
					log.Error("Failed to process AKS cluster", "name", *mc.Name, "error", err)
					mu.Lock()
					syncErrors = append(syncErrors, fmt.Errorf("cluster %s: %w", *mc.Name, err))
					mu.Unlock()
					return
				}

				mu.Lock()
				resources = append(resources, resource)
				mu.Unlock()
			}(cluster)
		}
	}

	wg.Wait()

	if len(syncErrors) > 0 {
		log.Warn("Some clusters failed to sync", "errors", len(syncErrors))
		// Continue with the clusters that succeeded
	}

	log.Info("Found AKS clusters", "count", len(resources))
	return resources, nil
}

func processCluster(_ context.Context, cluster *armcontainerservice.ManagedCluster, subscriptionID string, tenantID string) (api.AgentResource, error) {
	resourceGroup := extractResourceGroupFromID(*cluster.ID)
	metadata := initClusterMetadata(cluster, subscriptionID, resourceGroup, tenantID)

	// Build console URL
	consoleUrl := fmt.Sprintf("https://portal.azure.com/#@/resource%s", *cluster.ID)
	metadata[kinds.CtrlplaneMetadataLinks] = fmt.Sprintf("{ \"Azure Portal\": \"%s\" }", consoleUrl)

	certificateAuthorityData := ""
	// The Azure SDK may not expose KubeConfig directly, we'll handle this gracefully
	
	endpoint := ""
	if cluster.Properties.PrivateFQDN != nil {
		endpoint = *cluster.Properties.PrivateFQDN
	} else if cluster.Properties.Fqdn != nil {
		endpoint = *cluster.Properties.Fqdn
	}

	return api.AgentResource{
		Version:    "ctrlplane.dev/kubernetes/cluster/v1",
		Kind:       "AzureKubernetesService",
		Name:       *cluster.Name,
		Identifier: *cluster.ID,
		Config: map[string]any{
			"name":    *cluster.Name,
			"version": *cluster.Properties.KubernetesVersion,
			"server": map[string]any{
				"endpoint":                 endpoint,
				"certificateAuthorityData": certificateAuthorityData,
			},

			// Provider-specific implementation details
			"azureKubernetesService": map[string]any{
				"subscriptionId": subscriptionID,
				"tenantId":       tenantID,
				"resourceGroup":  resourceGroup,
				"location":       *cluster.Location,
				"status":         *cluster.Properties.ProvisioningState,
				"skuTier":        string(*cluster.SKU.Tier),
			},
		},
		Metadata: metadata,
	}, nil
}

func initClusterMetadata(cluster *armcontainerservice.ManagedCluster, subscriptionID, resourceGroup string, tenantID string) map[string]string {
	version, err := semver.NewVersion(*cluster.Properties.KubernetesVersion)
	if err != nil {
		log.Error("Failed to parse Kubernetes version", "version", *cluster.Properties.KubernetesVersion, "error", err)
	}

	normalizedStatus := "unknown"
	switch *cluster.Properties.ProvisioningState {
	case "Succeeded":
		normalizedStatus = "running"
	case "Creating":
		normalizedStatus = "creating"
	case "Updating":
		normalizedStatus = "updating"
	case "Deleting":
		normalizedStatus = "deleting"
	case "Failed":
		normalizedStatus = "failed"
	}

	metadata := map[string]string{
		"network/type": "vnet",

		kinds.K8SMetadataType:   "aks",
		kinds.K8SMetadataName:   *cluster.Name,
		kinds.K8SMetadataStatus: normalizedStatus,

		kinds.K8SMetadataVersion:           fmt.Sprintf("%d.%d.%d", version.Major(), version.Minor(), version.Patch()),
		kinds.K8SMetadataVersionMajor:      strconv.FormatUint(uint64(version.Major()), 10),
		kinds.K8SMetadataVersionMinor:      strconv.FormatUint(uint64(version.Minor()), 10),
		kinds.K8SMetadataVersionPatch:      strconv.FormatUint(uint64(version.Patch()), 10),
		kinds.K8SMetadataVersionPrerelease: version.Prerelease(),

		"kubernetes/location": *cluster.Location,
		"kubernetes/endpoint": getEndpoint(cluster),

		"azure/subscription":    subscriptionID,
		"azure/tenant":          tenantID,
		"azure/resource-group":  resourceGroup,
		"azure/resource-type":   "Microsoft.ContainerService/managedClusters",
		"azure/location":        *cluster.Location,
		"azure/status":          *cluster.Properties.ProvisioningState,
		"azure/id":              *cluster.ID,
		"azure/console-url":     fmt.Sprintf("https://portal.azure.com/#@/resource%s", *cluster.ID),
	}

	// Process creation time if available
	if cluster.SystemData != nil && cluster.SystemData.CreatedAt != nil {
		metadata[kinds.K8SMetadataCreated] = cluster.SystemData.CreatedAt.Format(time.RFC3339)
	}

	// Add node pool information
	if cluster.Properties.AgentPoolProfiles != nil {
		metadata["kubernetes/node-pool-count"] = strconv.Itoa(len(cluster.Properties.AgentPoolProfiles))
		
		totalNodeCount := 0
		for i, pool := range cluster.Properties.AgentPoolProfiles {
			metadata[fmt.Sprintf("kubernetes/node-pool/%d/name", i)] = *pool.Name
			metadata[fmt.Sprintf("kubernetes/node-pool/%d/vm-size", i)] = *pool.VMSize
			metadata[fmt.Sprintf("kubernetes/node-pool/%d/os-type", i)] = string(*pool.OSType)
			metadata[fmt.Sprintf("kubernetes/node-pool/%d/mode", i)] = string(*pool.Mode)
			
			if pool.Count != nil {
				nodeCount := int(*pool.Count)
				metadata[fmt.Sprintf("kubernetes/node-pool/%d/count", i)] = strconv.Itoa(nodeCount)
				totalNodeCount += nodeCount
			}
			
			if pool.EnableAutoScaling != nil && *pool.EnableAutoScaling {
				metadata[fmt.Sprintf("kubernetes/node-pool/%d/autoscaling", i)] = "enabled"
				if pool.MinCount != nil {
					metadata[fmt.Sprintf("kubernetes/node-pool/%d/min-count", i)] = strconv.Itoa(int(*pool.MinCount))
				}
				if pool.MaxCount != nil {
					metadata[fmt.Sprintf("kubernetes/node-pool/%d/max-count", i)] = strconv.Itoa(int(*pool.MaxCount))
				}
			} else {
				metadata[fmt.Sprintf("kubernetes/node-pool/%d/autoscaling", i)] = "disabled"
			}
			
			if pool.OSDiskSizeGB != nil {
				metadata[fmt.Sprintf("kubernetes/node-pool/%d/os-disk-size-gb", i)] = strconv.Itoa(int(*pool.OSDiskSizeGB))
			}
		}
		
		metadata["kubernetes/total-node-count"] = strconv.Itoa(totalNodeCount)
	}

	// Network profile
	if cluster.Properties.NetworkProfile != nil {
		if cluster.Properties.NetworkProfile.NetworkPlugin != nil {
			metadata["network/plugin"] = string(*cluster.Properties.NetworkProfile.NetworkPlugin)
		}
		if cluster.Properties.NetworkProfile.NetworkPolicy != nil {
			metadata["network/policy"] = string(*cluster.Properties.NetworkProfile.NetworkPolicy)
		}
		if cluster.Properties.NetworkProfile.PodCidr != nil {
			metadata["network/pod-cidr"] = *cluster.Properties.NetworkProfile.PodCidr
		}
		if cluster.Properties.NetworkProfile.ServiceCidr != nil {
			metadata["network/service-cidr"] = *cluster.Properties.NetworkProfile.ServiceCidr
		}
		if cluster.Properties.NetworkProfile.DNSServiceIP != nil {
			metadata["network/dns-service-ip"] = *cluster.Properties.NetworkProfile.DNSServiceIP
		}
		if cluster.Properties.NetworkProfile.DockerBridgeCidr != nil {
			metadata["network/docker-bridge-cidr"] = *cluster.Properties.NetworkProfile.DockerBridgeCidr
		}
	}

	// Add-ons
	if cluster.Properties.AddonProfiles != nil {
		for addonName, addon := range cluster.Properties.AddonProfiles {
			if addon.Enabled != nil {
				metadata[fmt.Sprintf("kubernetes/addon/%s", strings.ToLower(addonName))] = strconv.FormatBool(*addon.Enabled)
			}
		}
	}

	// Tags
	if cluster.Tags != nil {
		for key, value := range cluster.Tags {
			if value != nil {
				metadata[fmt.Sprintf("tags/%s", key)] = *value
			}
		}
	}

	return metadata
}

func getEndpoint(cluster *armcontainerservice.ManagedCluster) string {
	if cluster.Properties.PrivateFQDN != nil {
		return *cluster.Properties.PrivateFQDN
	}
	if cluster.Properties.Fqdn != nil {
		return *cluster.Properties.Fqdn
	}
	return ""
}

func extractResourceGroupFromID(id string) string {
	// The format of the resource ID is: 
	// /subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.ContainerService/managedClusters/{clusterName}
	parts := strings.Split(id, "/")
	for i, part := range parts {
		if strings.EqualFold(part, "resourceGroups") && i+1 < len(parts) {
			return parts[i+1]
		}
	}
	return ""
}

var relationshipRules = []api.CreateResourceRelationshipRule{
	{
		Reference:      "network",
		Name:           "Azure Cluster Network",
		DependencyType: api.ProvisionedIn,

		SourceKind:    "AzureKubernetesService",
		SourceVersion: "ctrlplane.dev/kubernetes/cluster/v1",
		TargetKind:    "AzureNetwork",
		TargetVersion: "ctrlplane.dev/network/v1",

		MetadataKeysMatch: []string{"azure/subscription", "azure/resource-group"},
	},
}

func upsertToCtrlplane(ctx context.Context, resources []api.AgentResource, subscriptionID, name *string) error {
	if *name == "" {
		*name = fmt.Sprintf("azure-aks-%s", *subscriptionID)
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
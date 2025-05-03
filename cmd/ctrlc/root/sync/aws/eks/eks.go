package eks

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/Masterminds/semver"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/ec2"
	"github.com/aws/aws-sdk-go-v2/service/eks"
	"github.com/aws/aws-sdk-go-v2/service/eks/types"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

// A list of all AWS regions as fallback
var allRegions = []string{
	"us-east-1", "us-east-2", "us-west-1", "us-west-2",
	"ap-south-1", "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
	"ap-southeast-1", "ap-southeast-2", "ap-southeast-3", "ap-east-1",
	"ca-central-1", "eu-central-1", "eu-west-1", "eu-west-2", "eu-west-3",
	"eu-north-1", "eu-south-1", "sa-east-1", "me-south-1", "af-south-1",
}

// NewSyncEKSCmd creates a new cobra command for syncing EKS clusters
func NewSyncEKSCmd() *cobra.Command {
	var regions []string
	var name string

	cmd := &cobra.Command{
		Use:   "eks",
		Short: "Sync Amazon Elastic Kubernetes Service clusters into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure AWS credentials are configured via environment variables or AWS CLI
			
			# Sync all EKS clusters from a region
			$ ctrlc sync aws eks --region us-west-2
			
			# Sync all EKS clusters from multiple regions
			$ ctrlc sync aws eks --region us-west-2 --region us-east-1
			
			# Sync all EKS clusters from all regions
			$ ctrlc sync aws eks
		`),
		RunE:    runSync(&regions, &name),
	}

	cmd.Flags().StringVarP(&name, "provider", "p", "", "Name of the resource provider")
	cmd.Flags().StringSliceVarP(&regions, "region", "r", []string{}, "AWS Region(s)")
	
	return cmd
}

// getRegions returns a list of regions to use based on the provided flags
func getRegions(ctx context.Context, regions []string) ([]string, error) {
	if len(regions) > 0 {
		return regions, nil
	}
	
	// Dynamically discover available regions using EC2 API
	log.Info("No regions specified, discovering available regions...")
	
	// Load AWS config with default region to use for discovery
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"))
	if err != nil {
		log.Warn("Failed to load AWS config for region discovery, using hardcoded list", "error", err)
		return allRegions, nil
	}
	
	// Create EC2 client for region discovery
	ec2Client := ec2.NewFromConfig(cfg)
	
	// Call DescribeRegions to get all available regions
	resp, err := ec2Client.DescribeRegions(ctx, &ec2.DescribeRegionsInput{
		AllRegions: nil, // Set to true to include disabled regions
	})
	if err != nil {
		log.Warn("Failed to discover regions, using hardcoded list", "error", err)
		return allRegions, nil
	}
	
	// Extract region names from response
	discoveredRegions := make([]string, 0, len(resp.Regions))
	for _, region := range resp.Regions {
		if region.RegionName != nil {
			discoveredRegions = append(discoveredRegions, *region.RegionName)
		}
	}
	
	if len(discoveredRegions) == 0 {
		log.Warn("No regions discovered, using hardcoded list")
		return allRegions, nil
	}
	
	log.Info("Discovered AWS regions", "count", len(discoveredRegions))
	return discoveredRegions, nil
}

func runSync(regions *[]string, name *string) func(cmd *cobra.Command, args []string) error {
	return func(cmd *cobra.Command, args []string) error {
		ctx := context.Background()
		
		// Get the regions to sync from
		regionsToSync, err := getRegions(ctx, *regions)
		if err != nil {
			return err
		}
		
		log.Info("Syncing EKS clusters", "regions", regionsToSync)
		
		// Process each region
		var allResources []api.AgentResource
		var mu sync.Mutex
		var wg sync.WaitGroup
		var syncErrors []error
		
		for _, r := range regionsToSync {
			wg.Add(1)
			go func(regionName string) {
				defer wg.Done()
				
				// Initialize AWS client for this region
				eksClient, err := initEKSClient(ctx, regionName)
				if err != nil {
					log.Error("Failed to initialize EKS client", "region", regionName, "error", err)
					mu.Lock()
					syncErrors = append(syncErrors, fmt.Errorf("region %s: %w", regionName, err))
					mu.Unlock()
					return
				}

				// List and process clusters for this region
				resources, err := processClusters(ctx, eksClient, regionName)
				if err != nil {
					log.Error("Failed to process clusters", "region", regionName, "error", err)
					mu.Lock()
					syncErrors = append(syncErrors, fmt.Errorf("region %s: %w", regionName, err))
					mu.Unlock()
					return
				}
				
				if len(resources) > 0 {
					mu.Lock()
					allResources = append(allResources, resources...)
					mu.Unlock()
				}
			}(r)
		}
		
		wg.Wait()
		
		if len(syncErrors) > 0 {
			log.Warn("Some regions failed to sync", "errors", len(syncErrors))
			// Continue with the regions that succeeded
		}
		
		if len(allResources) == 0 {
			log.Info("No EKS clusters found in the specified regions")
			return nil
		}
		
		// Use regions for name if none provided
		providerRegion := "all-regions"
		if regions != nil && len(*regions) > 0 {
			providerRegion = strings.Join(*regions, "-")
		}
		// Upsert resources to Ctrlplane
		return upsertToCtrlplane(ctx, allResources, &providerRegion, name)
	}
}

func initEKSClient(ctx context.Context, region string) (*eks.Client, error) {
	// Try to load AWS config with explicit credentials
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(region))
	if err != nil {
		log.Warn("Failed to load AWS config with default credentials, checking environment", "error", err)
		
		// If default config fails, try to get credentials from environment or other sources
		// This can help when AWS CLI works but the SDK has issues with credential discovery
		cfg, err = config.LoadDefaultConfig(ctx, 
			config.WithRegion(region),
			config.WithSharedConfigProfile("default"))
		
		if err != nil {
			return nil, fmt.Errorf("failed to load AWS config: %w", err)
		}
	}
	
	// Verify credentials are valid before proceeding
	credentials, err := cfg.Credentials.Retrieve(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to retrieve AWS credentials: %w", err)
	}

	log.Info("Successfully loaded AWS credentials", "region", region, "accessKeyId", credentials.AccessKeyID[:4]+"***")
	return eks.NewFromConfig(cfg), nil
}

func processClusters(ctx context.Context, eksClient *eks.Client, region string) ([]api.AgentResource, error) {
	var resources []api.AgentResource
	var nextToken *string

	for {
		resp, err := eksClient.ListClusters(ctx, &eks.ListClustersInput{
			NextToken: nextToken,
		})
		if err != nil {
			return nil, fmt.Errorf("failed to list EKS clusters: %w", err)
		}

		for _, clusterName := range resp.Clusters {
			cluster, err := eksClient.DescribeCluster(ctx, &eks.DescribeClusterInput{
				Name: &clusterName,
			})
			if err != nil {
				log.Error("Failed to describe cluster", "name", clusterName, "error", err)
				continue
			}

			resource, err := processCluster(ctx, cluster.Cluster, region)
			if err != nil {
				log.Error("Failed to process EKS cluster", "name", clusterName, "error", err)
				continue
			}
			resources = append(resources, resource)
		}

		if resp.NextToken == nil {
			break
		}
		nextToken = resp.NextToken
	}

	log.Info("Found EKS clusters", "region", region, "count", len(resources))
	return resources, nil
}

func processCluster(_ context.Context, cluster *types.Cluster, region string) (api.AgentResource, error) {
	metadata := initClusterMetadata(cluster, region)

	consoleUrl := fmt.Sprintf("https://%s.console.aws.amazon.com/eks/home?region=%s#/clusters/%s",
		region, region, *cluster.Name)
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"AWS Console\": \"%s\" }", consoleUrl)

	return api.AgentResource{
		Version:    "ctrlplane.dev/kubernetes/cluster/v1",
		Kind:       "AWSElasticKubernetesService",
		Name:       *cluster.Name,
		Identifier: *cluster.Arn,
		Config: map[string]any{
			"name":    *cluster.Name,
			"version": *cluster.Version,
			"server": map[string]any{
				"endpoint":                 *cluster.Endpoint,
				"certificateAuthorityData": *cluster.CertificateAuthority.Data,

				// Provider-specific implementation details
				"elasticKubernetesService": map[string]any{
					"arn":             *cluster.Arn,
					"region":          region,
					"status":          string(cluster.Status),
					"platformVersion": *cluster.PlatformVersion,
					"vpc":             *cluster.ResourcesVpcConfig.VpcId,
				},
			},
		},
		Metadata: metadata,
	}, nil
}

func initClusterMetadata(cluster *types.Cluster, region string) map[string]string {
	version, err := semver.NewVersion(*cluster.Version)
	if err != nil {
		log.Error("Failed to parse Kubernetes version", "version", *cluster.Version, "error", err)
	}

	metadata := map[string]string{
		"network/type": "vpc",
		"network/name": *cluster.ResourcesVpcConfig.VpcId,

		"kubernetes/type":          "eks",
		"kubernetes/name":          *cluster.Name,
		"kubernetes/version":       fmt.Sprintf("%d.%d.%d", version.Major(), version.Minor(), version.Patch()),
		"kubernetes/version/major": strconv.FormatUint(uint64(version.Major()), 10),
		"kubernetes/version/minor": strconv.FormatUint(uint64(version.Minor()), 10),
		"kubernetes/version/patch": strconv.FormatUint(uint64(version.Patch()), 10),
		"kubernetes/version/full":  *cluster.Version,
		"kubernetes/status":        string(cluster.Status),
		"kubernetes/endpoint":      *cluster.Endpoint,

		"aws/region":           region,
		"aws/resource-type":    "eks:cluster",
		"aws/status":           string(cluster.Status),
		"aws/platform-version": *cluster.PlatformVersion,
		"aws/arn":              *cluster.Arn,
	}

	if cluster.CreatedAt != nil {
		metadata["kubernetes/created"] = cluster.CreatedAt.Format(time.RFC3339)
	}

	// Network configuration
	if cluster.ResourcesVpcConfig != nil {
		metadata["network/vpc"] = *cluster.ResourcesVpcConfig.VpcId
		if len(cluster.ResourcesVpcConfig.SubnetIds) > 0 {
			metadata["network/subnet-count"] = strconv.Itoa(len(cluster.ResourcesVpcConfig.SubnetIds))
			metadata["network/subnets"] = strings.Join(cluster.ResourcesVpcConfig.SubnetIds, ",")
		}
	}

	// Logging configuration
	if cluster.Logging != nil && cluster.Logging.ClusterLogging != nil {
		for _, logging := range cluster.Logging.ClusterLogging {
			if logging.Enabled != nil && *logging.Enabled {
				for _, logType := range logging.Types {
					metadata[fmt.Sprintf("logging/%s", strings.ToLower(string(logType)))] = "enabled"
				}
			}
		}
	}

	return metadata
}

var relationshipRules = []api.CreateResourceRelationshipRule{
	{
		Reference:      "network",
		Name:           "AWS Cluster Network",
		DependencyType: api.ProvisionedIn,

		SourceKind:    "ctrlplane.dev/kubernetes/cluster/v1",
		SourceVersion: "AWSElasticKubernetesService",
		TargetKind:    "ctrlplane.dev/network/v1",
		TargetVersion: "AWSNetwork",

		MetadataKeysMatch: []string{"aws/region", "network/name"},
	},
}

func upsertToCtrlplane(ctx context.Context, resources []api.AgentResource, region, name *string) error {
	if *name == "" {
		*name = fmt.Sprintf("aws-eks-%s", *region)
	}

	apiURL := viper.GetString("url")
	apiKey := viper.GetString("api-key")
	workspaceId := viper.GetString("workspace")

	ctrlplaneClient, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
	if err != nil {
		return fmt.Errorf("failed to create API client: %w", err)
	}

	for _, rule := range relationshipRules {
		rule.WorkspaceId = workspaceId
		resp, err := ctrlplaneClient.UpsertResourceRelationshipRuleWithResponse(ctx, rule)
		if err != nil {
			log.Error("Failed to upsert resource relationship rule", "name", *name, "error", err)
		}
		if resp.StatusCode() != http.StatusOK {
			log.Error("Failed to upsert resource relationship rule", "name", *name, "status", resp.StatusCode(), "rule", rule)
		}
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

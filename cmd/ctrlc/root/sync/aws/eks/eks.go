package eks

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/Masterminds/semver"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/eks"
	"github.com/aws/aws-sdk-go-v2/service/eks/types"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

// NewSyncEKSCmd creates a new cobra command for syncing EKS clusters
func NewSyncEKSCmd() *cobra.Command {
	var region string
	var name string

	cmd := &cobra.Command{
		Use:   "eks",
		Short: "Sync Amazon Elastic Kubernetes Service clusters into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure AWS credentials are configured via environment variables or AWS CLI
			
			# Sync all EKS clusters from a region
			$ ctrlc sync aws eks --region us-west-2
		`),
		PreRunE: validateFlags(&region),
		RunE:    runSync(&region, &name),
	}

	cmd.Flags().StringVarP(&name, "provider", "p", "", "Name of the resource provider")
	cmd.Flags().StringVarP(&region, "region", "r", "", "AWS Region")
	cmd.MarkFlagRequired("region")

	return cmd
}

func validateFlags(region *string) func(cmd *cobra.Command, args []string) error {
	return func(cmd *cobra.Command, args []string) error {
		if *region == "" {
			return fmt.Errorf("region is required")
		}
		return nil
	}
}

func runSync(region, name *string) func(cmd *cobra.Command, args []string) error {
	return func(cmd *cobra.Command, args []string) error {
		log.Info("Syncing EKS clusters into Ctrlplane", "region", *region)

		ctx := context.Background()

		// Initialize AWS client
		eksClient, err := initEKSClient(ctx, *region)
		if err != nil {
			return err
		}

		// List and process clusters
		resources, err := processClusters(ctx, eksClient, *region)
		if err != nil {
			return err
		}

		// Upsert resources to Ctrlplane
		return upsertToCtrlplane(ctx, resources, region, name)
	}
}

func initEKSClient(ctx context.Context, region string) (*eks.Client, error) {
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(region))
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

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

	log.Info("Found EKS clusters", "count", len(resources))
	return resources, nil
}

func processCluster(_ context.Context, cluster *types.Cluster, region string) (api.AgentResource, error) {
	metadata := initClusterMetadata(cluster, region)

	consoleUrl := fmt.Sprintf("https://%s.console.aws.amazon.com/eks/home?region=%s#/clusters/%s",
		region, region, *cluster.Name)
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"AWS Console\": \"%s\" }", consoleUrl)

	return api.AgentResource{
		Version:    "ctrlplane.dev/kubernetes/cluster/v1",
		Kind:       "ElasticKubernetesService",
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
		SourceVersion: "ElasticKubernetesService",
		TargetKind:    "ctrlplane.dev/network/v1",
		TargetVersion: "AWSNetwork",

		MetadataKeysMatch: []string{"aws/region", "network/name"},
	},
}

func upsertToCtrlplane(ctx context.Context, resources []api.AgentResource, region, name *string) error {
	if *name == "" {
		*name = fmt.Sprintf("aws-eks-region-%s", *region)
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

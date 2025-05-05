package rds

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"sync"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/Masterminds/semver"
	"github.com/aws/aws-sdk-go-v2/service/rds"
	"github.com/aws/aws-sdk-go-v2/service/rds/types"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/aws/common"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/kinds"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

// NewSyncRDSCmd creates a new cobra command for syncing AWS RDS instances
func NewSyncRDSCmd() *cobra.Command {
	var regions []string
	var name string

	cmd := &cobra.Command{
		Use:   "rds",
		Short: "Sync Amazon Relational Database Service instances into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure AWS credentials are configured via environment variables or AWS CLI
			
			# Sync all RDS instances from a region
			$ ctrlc sync aws rds --region us-west-2
			
			# Sync all RDS instances from multiple regions
			$ ctrlc sync aws rds --region us-west-2 --region us-east-1
			
			# Sync all RDS instances from all regions
			$ ctrlc sync aws rds
		`),
		RunE: runSync(&regions, &name),
	}

	cmd.Flags().StringVarP(&name, "provider", "p", "", "Name of the resource provider")
	cmd.Flags().StringSliceVarP(&regions, "region", "r", []string{}, "AWS Region(s)")

	return cmd
}

func runSync(regions *[]string, name *string) func(cmd *cobra.Command, args []string) error {
	return func(cmd *cobra.Command, args []string) error {
		ctx := context.Background()

		// Get the regions to sync from using common package
		regionsToSync, err := common.GetRegions(ctx, *regions)
		if err != nil {
			return err
		}

		log.Info("Syncing RDS instances", "regions", regionsToSync)

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
				rdsClient, err := initRDSClient(ctx, regionName)
				if err != nil {
					log.Error("Failed to initialize RDS client", "region", regionName, "error", err)
					mu.Lock()
					syncErrors = append(syncErrors, fmt.Errorf("region %s: %w", regionName, err))
					mu.Unlock()
					return
				}

				// List and process instances for this region
				resources, err := processInstances(ctx, rdsClient, regionName)
				if err != nil {
					log.Error("Failed to process instances", "region", regionName, "error", err)
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
			log.Info("No RDS instances found in the specified regions")
			return nil
		}

		// Use regions for name if none provided
		providerRegion := "all-regions"
		if regions != nil && len(*regions) > 0 {
			providerRegion = strings.Join(*regions, "-")
		}

		// If name is not provided, try to get account ID to include in the provider name
		if *name == "" {
			// Get AWS account ID for provider name using common package
			cfg, err := common.InitAWSConfig(ctx, regionsToSync[0])
			if err != nil {
				log.Warn("Failed to load AWS config for account ID retrieval", "error", err)
				*name = fmt.Sprintf("aws-rds-%s", providerRegion)
			} else {
				accountID, err := common.GetAccountID(ctx, cfg)
				if err == nil {
					log.Info("Retrieved AWS account ID", "account_id", accountID)
					*name = fmt.Sprintf("aws-rds-%s-%s", accountID, providerRegion)
				} else {
					log.Warn("Failed to get AWS account ID", "error", err)
					*name = fmt.Sprintf("aws-rds-%s", providerRegion)
				}
			}
		}

		// Upsert resources to Ctrlplane
		return upsertToCtrlplane(ctx, allResources, &providerRegion, name)
	}
}

func initRDSClient(ctx context.Context, region string) (*rds.Client, error) {
	// Use common package to initialize AWS config
	cfg, err := common.InitAWSConfig(ctx, region)
	if err != nil {
		return nil, err
	}

	return rds.NewFromConfig(cfg), nil
}

func processInstances(ctx context.Context, rdsClient *rds.Client, region string) ([]api.AgentResource, error) {
	var resources []api.AgentResource
	var marker *string

	for {
		resp, err := rdsClient.DescribeDBInstances(ctx, &rds.DescribeDBInstancesInput{
			Marker: marker,
		})
		if err != nil {
			return nil, fmt.Errorf("failed to list RDS instances: %w", err)
		}

		for _, instance := range resp.DBInstances {
			resource, err := processInstance(ctx, &instance, region)
			if err != nil {
				log.Error("Failed to process RDS instance", "identifier", *instance.DBInstanceIdentifier, "error", err)
				continue
			}
			resources = append(resources, resource)
		}

		if resp.Marker == nil {
			break
		}
		marker = resp.Marker
	}

	log.Info("Found RDS instances", "region", region, "count", len(resources))
	return resources, nil
}

func processInstance(_ context.Context, instance *types.DBInstance, region string) (api.AgentResource, error) {
	// Get default port based on engine
	port := int32(5432) // Default to PostgreSQL port
	if instance.Endpoint != nil && instance.Endpoint.Port != nil && *instance.Endpoint.Port != 0 {
		port = *instance.Endpoint.Port
	}

	// Get host
	host := ""
	if instance.Endpoint != nil && instance.Endpoint.Address != nil {
		host = *instance.Endpoint.Address
	}

	// Build ARN if not available
	identifier := ""
	if instance.DBInstanceArn != nil {
		identifier = *instance.DBInstanceArn
	} else if instance.DBInstanceIdentifier != nil {
		identifier = fmt.Sprintf("arn:aws:rds:%s::%s", region, *instance.DBInstanceIdentifier)
	}

	// Build console URL
	consoleUrl := fmt.Sprintf("https://%s.console.aws.amazon.com/rds/home?region=%s#database:id=%s;is-cluster=false",
		region, region, *instance.DBInstanceIdentifier)

	metadata := buildInstanceMetadata(instance, region, host, int(port), consoleUrl)

	return api.AgentResource{
		Version:    "ctrlplane.dev/database/v1",
		Kind:       "AWSRelationalDatabaseService",
		Name:       *instance.DBInstanceIdentifier,
		Identifier: identifier,
		Config: map[string]any{
			"name": *instance.DBInstanceIdentifier,
			"host": host,
			"port": port,
			"ssl":  true, // RDS uses SSL by default

			// Provider-specific implementation details
			"awsRelationalDatabaseService": map[string]any{
				"engine":        *instance.Engine,
				"engineVersion": *instance.EngineVersion,
				"region":        region,
				"status":        *instance.DBInstanceStatus,
				"storageType":   *instance.StorageType,
				"dbName":        getStringPtrValue(instance.DBName),
				"instanceClass": *instance.DBInstanceClass,
				"multiAZ":       instance.MultiAZ,
			},
		},
		Metadata: metadata,
	}, nil
}

// Helper function to safely get string value from pointer
func getStringPtrValue(ptr *string) string {
	if ptr == nil {
		return ""
	}
	return *ptr
}

// getNormalizedDBType returns a normalized database type from the RDS engine
func getNormalizedDBType(engine string) string {
	engineLower := strings.ToLower(engine)

	switch {
	case strings.Contains(engineLower, "mysql"):
		return "mysql"
	case strings.Contains(engineLower, "postgres"):
		return "postgres"
	case strings.Contains(engineLower, "maria"):
		return "mariadb"
	case strings.Contains(engineLower, "oracle"):
		return "oracle"
	case strings.Contains(engineLower, "sqlserver"):
		return "sqlserver"
	case strings.Contains(engineLower, "aurora"):
		// For Aurora, determine if it's MySQL or PostgreSQL compatible
		if strings.Contains(engineLower, "postgresql") {
			return "postgres"
		}
		return "mysql" // Default Aurora is MySQL compatible
	default:
		return engineLower
	}
}

// parseEngineVersion parses the RDS engine version into semver components
func parseEngineVersion(engineVersion string) (major, minor, patch string, prerelease string) {
	// Handle special case for Aurora MySQL which has format like "8.0.mysql_aurora.3.07.1"
	if strings.Contains(engineVersion, "mysql_aurora") || strings.Contains(engineVersion, "postgresql_aurora") {
		parts := strings.Split(engineVersion, ".")
		if len(parts) >= 2 {
			// For Aurora, use the MySQL/PostgreSQL compatibility version as the primary version
			major = parts[0]
			minor = parts[1]

			// Set Aurora version as prerelease to preserve it but prioritize DB version
			if len(parts) >= 4 {
				auroraVersion := strings.Join(parts[3:], ".")
				prerelease = "aurora_" + auroraVersion
			}

			// Default patch to 0 if not available
			patch = "0"

			return
		}
	}

	// For standard version strings, try to parse with semver library
	cleanVersion := engineVersion
	// Remove any non-semver compatible parts
	if idx := strings.Index(cleanVersion, "-"); idx > 0 {
		prerelease = cleanVersion[idx+1:]
		cleanVersion = cleanVersion[:idx]
	}

	// Try to parse with semver
	v, err := semver.NewVersion(cleanVersion)
	if err == nil {
		major = strconv.FormatInt(v.Major(), 10)
		minor = strconv.FormatInt(v.Minor(), 10)
		patch = strconv.FormatInt(v.Patch(), 10)
		if v.Prerelease() != "" && prerelease == "" {
			prerelease = v.Prerelease()
		}
		return
	}

	// Fallback to manual parsing if semver fails
	versionParts := strings.Split(engineVersion, ".")

	if len(versionParts) >= 1 {
		major = versionParts[0]
	}

	if len(versionParts) >= 2 {
		minor = versionParts[1]
	}

	if len(versionParts) >= 3 {
		// Check if there's a prerelease part (e.g., "28-R1")
		patchParts := strings.Split(versionParts[2], "-")
		patch = patchParts[0]

		if len(patchParts) > 1 && prerelease == "" {
			prerelease = strings.Join(patchParts[1:], "-")
		}
	}

	return
}

// buildInstanceMetadata builds the metadata map for an RDS instance
func buildInstanceMetadata(instance *types.DBInstance, region, host string, port int, consoleUrl string) map[string]string {
	// Get normalized database type
	dbType := getNormalizedDBType(*instance.Engine)

	major, minor, patch, prerelease := parseEngineVersion(*instance.EngineVersion)
	metadata := map[string]string{
		kinds.DBMetadataType:    dbType,
		kinds.DBMetadataName:    *instance.DBInstanceIdentifier,
		kinds.DBMetadataRegion:  region,
		kinds.DBMetadataState:   *instance.DBInstanceStatus,
		kinds.DBMetadataVersion: *instance.EngineVersion,
		kinds.DBMetadataHost:    host,
		kinds.DBMetadataPort:    strconv.Itoa(port),
		kinds.DBMetadataSSL:     "true",
		kinds.DBMetadataMultiAZ: strconv.FormatBool(*instance.MultiAZ),

		kinds.DBMetadataVersionMajor:      major,
		kinds.DBMetadataVersionMinor:      minor,
		kinds.DBMetadataVersionPatch:      patch,
		kinds.DBMetadataVersionPrerelease: prerelease,

		"aws/region":        region,
		"aws/resource-type": "rds",
		"aws/status":        *instance.DBInstanceStatus,
		"aws/console-url":   consoleUrl,
		"aws/engine":        *instance.Engine,
		"aws/db-type":       dbType,

		"compute/instance-class": *instance.DBInstanceClass,
		"compute/multi-az":       strconv.FormatBool(*instance.MultiAZ),

		kinds.CtrlplaneMetadataLinks: fmt.Sprintf("{ \"AWS Console\": \"%s\" }", consoleUrl),
	}

	// Add storage information
	if instance.AllocatedStorage != nil && *instance.AllocatedStorage != 0 {
		metadata["compute/storage-allocated-gb"] = strconv.FormatInt(int64(*instance.AllocatedStorage), 10)
	}
	if instance.StorageType != nil {
		metadata["compute/storage-type"] = *instance.StorageType
	}
	if instance.Iops != nil {
		metadata["compute/storage-iops"] = strconv.FormatInt(int64(*instance.Iops), 10)
	}

	// Add backup information
	if instance.BackupRetentionPeriod != nil && *instance.BackupRetentionPeriod != 0 {
		metadata[kinds.DBMetadataBackupRetention] = strconv.FormatInt(int64(*instance.BackupRetentionPeriod), 10)
	}
	if instance.PreferredBackupWindow != nil {
		metadata[kinds.DBMetadataBackupWindow] = *instance.PreferredBackupWindow
	}

	// Add database name if available
	if instance.DBName != nil {
		metadata[kinds.DBMetadataName] = *instance.DBName
	}
	if instance.LatestRestorableTime != nil {
		metadata["backup/latest-restorable"] = instance.LatestRestorableTime.String()
	}

	// Add maintenance information
	if instance.PreferredMaintenanceWindow != nil {
		metadata["maintenance/window"] = *instance.PreferredMaintenanceWindow
	}

	// Add endpoint information
	if instance.Endpoint != nil {
		if instance.Endpoint.Address != nil {
			metadata["network/endpoint"] = *instance.Endpoint.Address
		}
		if instance.Endpoint.Port != nil {
			metadata["network/port"] = strconv.Itoa(int(*instance.Endpoint.Port))
		}
		if instance.Endpoint.HostedZoneId != nil {
			metadata["network/hosted-zone-id"] = *instance.Endpoint.HostedZoneId
		}
	}

	// Add VPC and subnet information
	if instance.DBSubnetGroup != nil {
		if instance.DBSubnetGroup.VpcId != nil {
			metadata["network/vpc"] = *instance.DBSubnetGroup.VpcId
			metadata["network/name"] = *instance.DBSubnetGroup.VpcId
		}
		if instance.DBSubnetGroup.DBSubnetGroupName != nil {
			metadata["network/subnet-group"] = *instance.DBSubnetGroup.DBSubnetGroupName
		}
	}

	// For Aurora clusters
	if strings.Contains(strings.ToLower(*instance.Engine), "aurora") {
		metadata["aws/is-aurora"] = "true"
		if instance.DBClusterIdentifier != nil {
			metadata["aws/cluster-id"] = *instance.DBClusterIdentifier
		}
	} else {
		metadata["aws/is-aurora"] = "false"
	}

	for _, tag := range instance.TagList {
		if tag.Key != nil && tag.Value != nil {
			metadata[fmt.Sprintf("tags/%s", *tag.Key)] = *tag.Value
		}
	}

	return metadata
}

var relationshipRules = []api.CreateResourceRelationshipRule{
	{
		Reference:      "network",
		Name:           "AWS RDS Network",
		DependencyType: api.ProvisionedIn,

		SourceKind:    "ctrlplane.dev/database/v1",
		SourceVersion: "AWSRelationalDatabaseService",
		TargetKind:    "ctrlplane.dev/network/v1",
		TargetVersion: "AWSNetwork",

		MetadataKeysMatch: []string{"aws/region", "network/name"},
	},
}

// upsertToCtrlplane handles upserting resources to Ctrlplane
func upsertToCtrlplane(ctx context.Context, resources []api.AgentResource, region, name *string) error {
	if *name == "" {
		*name = fmt.Sprintf("aws-rds-%s", *region)
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

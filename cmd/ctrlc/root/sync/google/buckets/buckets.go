package buckets

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
	"google.golang.org/api/storage/v1"
)

// StorageBucket represents a Google Cloud Storage bucket
type StorageBucket struct {
	Name     string           `json:"name"`
	Location string           `json:"location"`
}

// NewSyncBucketsCmd creates a new cobra command for syncing Storage buckets
func NewSyncBucketsCmd() *cobra.Command {
	var project string
	var name string

	cmd := &cobra.Command{
		Use:   "google-buckets",
		Short: "Sync Google Storage buckets into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Google Cloud credentials are configured via environment variables or application default credentials
			
			# Sync all Storage buckets from a project
			$ ctrlc sync google-buckets --project my-project
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
		log.Info("Syncing Storage buckets into Ctrlplane", "project", *project)

		ctx := context.Background()

		// Initialize clients
		storageClient, err := initStorageClient(ctx)
		if err != nil {
			return err
		}

		// List and process buckets
		resources, err := processBuckets(ctx, storageClient, *project)
		if err != nil {
			return err
		}

		// Upsert resources to Ctrlplane
		return upsertToCtrlplane(ctx, resources, project, name)
	}
}

// initStorageClient creates a new Storage API client
func initStorageClient(ctx context.Context) (*storage.Service, error) {
	storageClient, err := storage.NewService(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create Storage API client: %w", err)
	}
	return storageClient, nil
}

// processBuckets lists and processes all Storage buckets in the project
func processBuckets(ctx context.Context, storageClient *storage.Service, project string) ([]api.AgentResource, error) {
	// List all buckets in the project
	buckets, err := storageClient.Buckets.List(project).Do()
	if err != nil {
		return nil, fmt.Errorf("failed to list buckets: %w", err)
	}

	log.Info("Found buckets", "count", len(buckets.Items))

	resources := []api.AgentResource{}
	for _, bucket := range buckets.Items {
		resource, err := processBucket(ctx, storageClient, bucket, project)
		if err != nil {
			log.Error("Failed to process bucket", "name", bucket.Name, "error", err)
			continue
		}
		resources = append(resources, resource)
	}

	return resources, nil
}

// processBucket handles processing of a single Storage bucket
func processBucket(_ context.Context, storageClient *storage.Service, bucket *storage.Bucket, project string) (api.AgentResource, error) {
	metadata := initBucketMetadata(bucket, project)
	
	// Process IAM policy if available
	err := processIamPolicy(storageClient, bucket, metadata)
	if err != nil {
		log.Error("Error processing IAM policy", "error", err)
	}
	
	// Process bucket details
	processStorageDetails(bucket, metadata)

	// Try to get bucket object statistics if available
	processBucketStats(storageClient, bucket, metadata)

	// Build console URL
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/storage/browser/%s?project=%s",
		bucket.Name, project)
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)

	return api.AgentResource{
		Version:    "ctrlplane.dev/storage/v1",
		Kind:       "GoogleBucket",
		Name:       bucket.Name,
		Identifier: fmt.Sprintf("projects/%s/buckets/%s", project, bucket.Name),
		Config: map[string]any{
			"name": bucket.Name,
			"googleStorage": map[string]any{
				"project":        project,
				"location":       bucket.Location,
				"storageClass":   bucket.StorageClass,
				"retentionPolicy": bucket.RetentionPolicy != nil,
				"versioning":     bucket.Versioning != nil && bucket.Versioning.Enabled,
			},
		},
		Metadata: metadata,
	}, nil
}

// initBucketMetadata initializes the base metadata for a bucket
func initBucketMetadata(bucket *storage.Bucket, project string) map[string]string {
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/storage/browser/%s?project=%s",
		bucket.Name, project)

	// Normalize time formats
	created := ""
	if bucket.TimeCreated != "" {
		if t, err := time.Parse(time.RFC3339, bucket.TimeCreated); err == nil {
			created = t.Format(time.RFC3339)
		} else {
			created = bucket.TimeCreated
		}
	}

	updated := ""
	if bucket.Updated != "" {
		if t, err := time.Parse(time.RFC3339, bucket.Updated); err == nil {
			updated = t.Format(time.RFC3339)
		} else {
			updated = bucket.Updated
		}
	}

	metadata := map[string]string{
		// Storage namespace
		"storage/type":               "google-bucket",
		"storage/bucket":             bucket.Name,
		"storage/location":           bucket.Location,
		"storage/location-type":      bucket.LocationType,
		"storage/storage-class":      bucket.StorageClass,
		"storage/created":            created,
		"storage/updated":            updated,
		"storage/versioning":         fmt.Sprintf("%v", bucket.Versioning != nil && bucket.Versioning.Enabled),
		
		// Google namespace
		"google/project":             project,
		"google/location":            bucket.Location,
		"google/location-type":       bucket.LocationType,
		"google/storage-class":       bucket.StorageClass,
		"google/console-url":         consoleUrl,
		"google/resource-type":       "storage.googleapis.com/Bucket",
		"google/metageneration":      strconv.FormatInt(bucket.Metageneration, 10),
	}

	if bucket.Etag != "" {
		metadata["google/etag"] = bucket.Etag
	}

	// Add billing export information if available
	if bucket.Billing != nil {
		metadata["storage/billing-requester-pays"] = strconv.FormatBool(bucket.Billing.RequesterPays)
	}

	// Add logging configuration if available
	if bucket.Logging != nil {
		if bucket.Logging.LogBucket != "" {
			metadata["storage/logging-bucket"] = bucket.Logging.LogBucket
		}
		if bucket.Logging.LogObjectPrefix != "" {
			metadata["storage/logging-prefix"] = bucket.Logging.LogObjectPrefix
		}
	}

	// Add website configuration if available
	if bucket.Website != nil {
		if bucket.Website.MainPageSuffix != "" {
			metadata["storage/website-main-page"] = bucket.Website.MainPageSuffix
		}
		if bucket.Website.NotFoundPage != "" {
			metadata["storage/website-not-found-page"] = bucket.Website.NotFoundPage
		}
		metadata["storage/website-enabled"] = "true"
	}

	// Add public access prevention information
	if bucket.IamConfiguration != nil && bucket.IamConfiguration.PublicAccessPrevention != "" {
		metadata["storage/public-access-prevention"] = bucket.IamConfiguration.PublicAccessPrevention
		
		// Add uniform bucket-level access information
		if bucket.IamConfiguration.UniformBucketLevelAccess != nil {
			metadata["storage/uniform-bucket-access"] = strconv.FormatBool(bucket.IamConfiguration.UniformBucketLevelAccess.Enabled)
			if bucket.IamConfiguration.UniformBucketLevelAccess.LockedTime != "" {
				metadata["storage/uniform-bucket-access-locked-time"] = bucket.IamConfiguration.UniformBucketLevelAccess.LockedTime
			}
		}
	}

	// Add default event-based hold if set
	if bucket.DefaultEventBasedHold {
		metadata["storage/default-event-based-hold"] = "true"
	}

	// Add default KMS key if available
	if bucket.Encryption != nil && bucket.Encryption.DefaultKmsKeyName != "" {
		metadata["storage/kms-key"] = bucket.Encryption.DefaultKmsKeyName
		metadata["security/encryption"] = "customer-managed-key"
	} else {
		metadata["security/encryption"] = "google-managed"
	}

	// Add CORS configuration summary if available
	if len(bucket.Cors) > 0 {
		origins := make(map[string]bool)
		methods := make(map[string]bool)
		for _, cors := range bucket.Cors {
			for _, origin := range cors.Origin {
				origins[origin] = true
			}
			for _, method := range cors.Method {
				methods[method] = true
			}
		}

		// Convert maps to sorted slices for deterministic output
		originList := make([]string, 0, len(origins))
		for origin := range origins {
			originList = append(originList, origin)
		}
		sort.Strings(originList)

		methodList := make([]string, 0, len(methods))
		for method := range methods {
			methodList = append(methodList, method)
		}
		sort.Strings(methodList)

		if len(originList) > 0 {
			metadata["storage/cors-origins"] = strings.Join(originList, ",")
		}
		if len(methodList) > 0 {
			metadata["storage/cors-methods"] = strings.Join(methodList, ",")
		}
	}
	
	return metadata
}

// processIamPolicy processes and adds IAM policy information to metadata
func processIamPolicy(storageClient *storage.Service, bucket *storage.Bucket, metadata map[string]string) error {
	policy, err := storageClient.Buckets.GetIamPolicy(bucket.Name).Do()
	if err != nil {
		return err
	}

	if policy != nil && policy.Bindings != nil {
		roleUsers := make(map[string][]string)
		
		for _, binding := range policy.Bindings {
			if binding.Members != nil {
				roleUsers[binding.Role] = append(roleUsers[binding.Role], binding.Members...)
			}
		}

		// Sort roles for consistent output
		roles := make([]string, 0, len(roleUsers))
		for role := range roleUsers {
			roles = append(roles, role)
		}
		sort.Strings(roles)

		// Add up to 10 roles to metadata for visibility
		roleCount := 0
		for _, role := range roles {
			if roleCount >= 10 {
				break
			}
			
			// Simplify role name for metadata
			shortRole := role
			if strings.HasPrefix(role, "roles/") {
				shortRole = strings.TrimPrefix(role, "roles/")
			}
			
			// Sort members for consistent output
			members := roleUsers[role]
			sort.Strings(members)
			
			// Add role and members to metadata
			metadata[fmt.Sprintf("google/storage/iam/%s", shortRole)] = strings.Join(members, ",")
			roleCount++
		}

		// Total count of roles
		metadata["google/storage/iam-role-count"] = strconv.Itoa(len(roles))
	}

	return nil
}

// processStorageDetails processes storage-specific details and adds to metadata
func processStorageDetails(bucket *storage.Bucket, metadata map[string]string) {
	// Handle versioning
	if bucket.Versioning != nil && bucket.Versioning.Enabled {
		metadata["storage/versioning"] = "enabled"
	} else {
		metadata["storage/versioning"] = "disabled"
	}

	// Handle lifecycle rules
	if bucket.Lifecycle != nil && bucket.Lifecycle.Rule != nil {
		metadata["storage/lifecycle-rules"] = strconv.Itoa(len(bucket.Lifecycle.Rule))
		
		// Extract some details about lifecycle rules
		for i, rule := range bucket.Lifecycle.Rule {
			if rule.Action != nil && rule.Action.Type != "" {
				metadata[fmt.Sprintf("storage/lifecycle/%d/action", i)] = rule.Action.Type
				
				if rule.Action.Type == "SetStorageClass" && rule.Action.StorageClass != "" {
					metadata[fmt.Sprintf("storage/lifecycle/%d/storage-class", i)] = rule.Action.StorageClass
				}
			}
			
			// Add conditions if present
			if rule.Condition != nil {
				if rule.Condition.Age != nil && *rule.Condition.Age > 0 {
					metadata[fmt.Sprintf("storage/lifecycle/%d/age-days", i)] = strconv.FormatInt(*rule.Condition.Age, 10)
				}
				if rule.Condition.CreatedBefore != "" {
					metadata[fmt.Sprintf("storage/lifecycle/%d/created-before", i)] = rule.Condition.CreatedBefore
				}
				if rule.Condition.NumNewerVersions > 0 {
					metadata[fmt.Sprintf("storage/lifecycle/%d/newer-versions", i)] = strconv.FormatInt(rule.Condition.NumNewerVersions, 10)
				}
				if rule.Condition.IsLive != nil {
					metadata[fmt.Sprintf("storage/lifecycle/%d/is-live", i)] = strconv.FormatBool(*rule.Condition.IsLive)
				}
			}
		}
	}

	// Handle CORS configuration
	if bucket.Cors != nil {
		metadata["storage/cors-enabled"] = "true"
		metadata["storage/cors-rules"] = strconv.Itoa(len(bucket.Cors))
	}

	// Handle retention policy
	if bucket.RetentionPolicy != nil {
		metadata["storage/retention-policy"] = "enabled"
		metadata["storage/retention-period"] = strconv.FormatInt(bucket.RetentionPolicy.RetentionPeriod, 10)
		
		retentionDays := bucket.RetentionPolicy.RetentionPeriod / 86400 // Convert seconds to days
		if retentionDays > 0 {
			metadata["storage/retention-days"] = strconv.FormatInt(retentionDays, 10)
		}
		
		if bucket.RetentionPolicy.EffectiveTime != "" {
			metadata["storage/retention-effective-time"] = bucket.RetentionPolicy.EffectiveTime
		}
	}

	// Handle encryption
	if bucket.Encryption != nil && bucket.Encryption.DefaultKmsKeyName != "" {
		metadata["storage/encryption"] = "customer-managed"
		metadata["storage/encryption-key"] = bucket.Encryption.DefaultKmsKeyName
	} else {
		metadata["storage/encryption"] = "google-managed"
	}

	// Handle labels
	if bucket.Labels != nil {
		for key, value := range bucket.Labels {
			metadata[fmt.Sprintf("google/storage/label/%s", key)] = value
		}
		metadata["google/storage/label-count"] = strconv.Itoa(len(bucket.Labels))
	}
	
	// Handle autoclass if set
	if bucket.Autoclass != nil {
		metadata["storage/autoclass-enabled"] = strconv.FormatBool(bucket.Autoclass.Enabled)
		if bucket.Autoclass.ToggleTime != "" {
			metadata["storage/autoclass-toggle-time"] = bucket.Autoclass.ToggleTime
		}
	}
}

// processBucketStats fetches and processes statistics about the bucket
func processBucketStats(storageClient *storage.Service, bucket *storage.Bucket, metadata map[string]string) {
	// Get bucket metadata including object count and size
	// We'll limit to just a few items to get the stats without listing all objects
	objects, err := storageClient.Objects.List(bucket.Name).MaxResults(1).Do()
	if err != nil {
		log.Error("Failed to get bucket statistics", "bucket", bucket.Name, "error", err)
		return
	}

	// Try to add basic statistics if available
	if objects != nil {
		if objects.NextPageToken != "" {
			metadata["storage/has-objects"] = "true"
		} else if len(objects.Items) == 0 {
			metadata["storage/has-objects"] = "false"
			metadata["storage/object-count"] = "0"
			metadata["storage/size-bytes"] = "0"
			metadata["storage/size-mb"] = "0"
		}
	}
}

// upsertToCtrlplane handles upserting resources to Ctrlplane
func upsertToCtrlplane(ctx context.Context, resources []api.AgentResource, project, name *string) error {
	if *name == "" {
		*name = fmt.Sprintf("google-buckets-project-%s", *project)
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
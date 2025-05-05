package secrets

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
	"google.golang.org/api/secretmanager/v1"
)

// NewSyncSecretsCmd creates a new cobra command for syncing Google Secret Manager secrets
func NewSyncSecretsCmd() *cobra.Command {
	var project string
	var name string

	cmd := &cobra.Command{
		Use:   "secrets",
		Short: "Sync Google Secret Manager secrets into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Google Cloud credentials are configured via environment variables or application default credentials
			
			# Sync all Secret Manager secrets from a project
			$ ctrlc sync google-cloud secrets --project my-project
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
		log.Info("Syncing Google Secret Manager secrets into Ctrlplane", "project", *project)

		ctx := context.Background()

		// Initialize Secret Manager client
		secretClient, err := initSecretManagerClient(ctx)
		if err != nil {
			return err
		}

		// List and process secrets
		resources, err := processSecrets(ctx, secretClient, *project)
		if err != nil {
			return err
		}

		// Upsert resources to Ctrlplane
		return upsertToCtrlplane(ctx, resources, project, name)
	}
}

// initSecretManagerClient creates a new Secret Manager client
func initSecretManagerClient(ctx context.Context) (*secretmanager.Service, error) {
	secretClient, err := secretmanager.NewService(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create Secret Manager client: %w", err)
	}
	return secretClient, nil
}

// processSecrets lists and processes all secrets
func processSecrets(ctx context.Context, secretClient *secretmanager.Service, project string) ([]api.AgentResource, error) {
	// Build the parent name for listing secrets
	parent := fmt.Sprintf("projects/%s", project)

	resources := []api.AgentResource{}
	secretCount := 0
	pageToken := ""

	for {
		// List secrets with pagination
		call := secretClient.Projects.Secrets.List(parent)
		if pageToken != "" {
			call = call.PageToken(pageToken)
		}

		log.Info("Listing secrets", "parent", parent, "pageToken", pageToken, "secretCount", secretCount)

		response, err := call.Do()
		if err != nil {
			return nil, fmt.Errorf("failed to list secrets: %w", err)
		}

		// Process secrets from current page
		for _, secret := range response.Secrets {
			resource, err := processSecret(ctx, secretClient, secret, project)
			if err != nil {
				log.Error("Failed to process secret", "name", secret.Name, "error", err)
				continue
			}
			resources = append(resources, resource)
			secretCount++
		}

		// Check if there are more pages
		if response.NextPageToken == "" {
			break
		}
		pageToken = response.NextPageToken
	}

	log.Info("Found secrets", "count", secretCount)
	return resources, nil
}

// processSecret handles processing of a single secret
func processSecret(_ context.Context, secretClient *secretmanager.Service, secret *secretmanager.Secret, project string) (api.AgentResource, error) {
	// Extract secret name from full resource name
	// Format: projects/{project}/secrets/{secret}
	secretName := getResourceName(secret.Name)

	// Fetch secret metadata & versions
	metadata := initSecretMetadata(secret, project)

	// Get the most recent version
	mostRecentVersion := ""
	versionsResponse, err := secretClient.Projects.Secrets.Versions.List(secret.Name).Do()
	if err == nil && len(versionsResponse.Versions) > 0 {
		// Find the most recent ENABLED version
		var latestVersion *secretmanager.SecretVersion
		for _, version := range versionsResponse.Versions {
			if version.State == "ENABLED" {
				if latestVersion == nil || version.CreateTime > latestVersion.CreateTime {
					latestVersion = version
				}
			}
		}

		if latestVersion != nil {
			// Get just the version ID from the full name
			// Format: projects/{project}/secrets/{secret}/versions/{version}
			parts := strings.Split(latestVersion.Name, "/")
			mostRecentVersion = parts[len(parts)-1]
			metadata["secret/latest-version"] = mostRecentVersion

			// Add version creation time
			if latestVersion.CreateTime != "" {
				creationTime, err := time.Parse(time.RFC3339, latestVersion.CreateTime)
				if err == nil {
					metadata["secret/latest-version-created"] = creationTime.Format(time.RFC3339)
				}
			}
		}
	}

	// Build console URL for the secret
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/security/secret-manager/secret/%s/versions?project=%s",
		secretName, project)
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)

	return api.AgentResource{
		Version:    "ctrlplane.dev/secret/v1",
		Kind:       "GoogleSecret",
		Name:       secretName,
		Identifier: secret.Name,
		Config: map[string]any{
			// Common cross-provider options
			"name":     secretName,
			"provider": "google",
			"type":     "secret",

			// Provider-specific implementation details
			"googleSecretManager": map[string]any{
				"project": project,
			},
		},
		Metadata: metadata,
	}, nil
}

// mapReplication converts the replication config to a simpler map
func mapReplication(replication *secretmanager.Replication) map[string]interface{} {
	if replication == nil {
		return nil
	}

	result := map[string]interface{}{
		"automatic": replication.Automatic != nil,
	}

	if replication.UserManaged != nil {
		replicas := []map[string]interface{}{}
		for _, replica := range replication.UserManaged.Replicas {
			replicaInfo := map[string]interface{}{
				"location": replica.Location,
			}
			if replica.CustomerManagedEncryption != nil {
				replicaInfo["customerManagedEncryption"] = map[string]interface{}{
					"kmsKeyName": replica.CustomerManagedEncryption.KmsKeyName,
				}
			}
			replicas = append(replicas, replicaInfo)
		}
		result["userManaged"] = map[string]interface{}{
			"replicas": replicas,
		}
	}

	return result
}

// mapTopics converts the topics to a simpler map
func mapTopics(topics []*secretmanager.Topic) []map[string]interface{} {
	if topics == nil {
		return nil
	}

	result := []map[string]interface{}{}
	for _, topic := range topics {
		topicInfo := map[string]interface{}{
			"name": topic.Name,
		}
		result = append(result, topicInfo)
	}

	return result
}

// initSecretMetadata initializes the base metadata for a secret
func initSecretMetadata(secret *secretmanager.Secret, project string) map[string]string {
	// Extract secret name from full resource name
	secretName := getResourceName(secret.Name)

	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/security/secret-manager/secret/%s/versions?project=%s",
		secretName, project)

	metadata := map[string]string{
		"secret/name":    secretName,
		"secret/type":    "google-secret-manager",
		"secret/project": project,

		"google/project":       project,
		"google/resource-type": "secretmanager.googleapis.com/Secret",
		"google/console-url":   consoleUrl,
	}

	// Add creation time
	if secret.CreateTime != "" {
		creationTime, err := time.Parse(time.RFC3339, secret.CreateTime)
		if err == nil {
			metadata["secret/created"] = creationTime.Format(time.RFC3339)
		} else {
			metadata["secret/created"] = secret.CreateTime
		}
	}

	// Add replication info
	if secret.Replication != nil {
		if secret.Replication.Automatic != nil {
			metadata["secret/replication"] = "automatic"
		} else if secret.Replication.UserManaged != nil {
			metadata["secret/replication"] = "user-managed"
			if len(secret.Replication.UserManaged.Replicas) > 0 {
				locations := []string{}
				for _, replica := range secret.Replication.UserManaged.Replicas {
					locations = append(locations, replica.Location)
				}
				metadata["secret/replication-locations"] = strings.Join(locations, ",")
			}
		}
	}

	// Add topic info if present
	if len(secret.Topics) > 0 {
		topicNames := []string{}
		for _, topic := range secret.Topics {
			topicName := getResourceName(topic.Name)
			topicNames = append(topicNames, topicName)
		}
		sort.Strings(topicNames)
		metadata["secret/topics"] = strings.Join(topicNames, ",")
		metadata["secret/topic-count"] = fmt.Sprintf("%d", len(secret.Topics))
	}

	// Add TTL if set
	if secret.Ttl != "" {
		metadata["secret/ttl"] = secret.Ttl
	}

	// Add labels
	if secret.Labels != nil {
		for key, value := range secret.Labels {
			metadata[fmt.Sprintf("labels/%s", key)] = value
		}
	}

	// Add annotations
	if secret.Annotations != nil {
		for key, value := range secret.Annotations {
			metadata[fmt.Sprintf("annotations/%s", key)] = value
		}
	}

	for key, value := range secret.Labels {
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

// upsertToCtrlplane handles upserting resources to Ctrlplane
func upsertToCtrlplane(ctx context.Context, resources []api.AgentResource, project, name *string) error {
	if *name == "" {
		*name = fmt.Sprintf("google-secrets-project-%s", *project)
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

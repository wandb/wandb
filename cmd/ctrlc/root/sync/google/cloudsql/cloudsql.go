package cloudsql

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
	"google.golang.org/api/sqladmin/v1"
)

func getInstanceHostAndPort(instance *sqladmin.DatabaseInstance) (string, int) {
	// Default port based on database type
	var port int
	switch {
	case strings.Contains(instance.DatabaseVersion, "POSTGRES"):
		port = 5432
	case strings.Contains(instance.DatabaseVersion, "MYSQL"):
		port = 3306
	case strings.Contains(instance.DatabaseVersion, "SQLSERVER"):
		port = 1433
	default:
		port = 5432
	}

	// Get the primary IP address
	var host string
	if instance.IpAddresses != nil {
		for _, ip := range instance.IpAddresses {
			if ip.Type == "PRIMARY" {
				host = ip.IpAddress
				break
			}
		}

		if host == "" {
			for _, ip := range instance.IpAddresses {
				if ip.Type == "PRIVATE" {
					host = ip.IpAddress
					break
				}
			}
		}

		if host == "" {
			log.Error("No IP address found for instance", "instance", instance.Name)
		}
	} else {
		log.Error("No IP addresses found for instance", "instance", instance.Name)
	}

	return host, port
}

func NewSyncCloudSQLCmd() *cobra.Command {
	var project string
	var providerName string

	cmd := &cobra.Command{
		Use:   "google-cloudsql",
		Short: "Sync Google Cloud SQL instances into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Google Cloud credentials are configured via environment variables or application default credentials
			
			# Sync all Cloud SQL instances from a project
			$ ctrlc sync google-cloudsql --project my-project
		`),
		PreRunE: func(cmd *cobra.Command, args []string) error {
			if project == "" {
				return fmt.Errorf("project is required")
			}
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			log.Info("Syncing Cloud SQL instances into Ctrlplane", "project", project)

			ctx := context.Background()

			// Create Cloud SQL Admin API client
			sqlService, err := sqladmin.NewService(ctx)
			if err != nil {
				return fmt.Errorf("failed to create Cloud SQL Admin client: %w", err)
			}

			// List all instances in project
			instances, err := sqlService.Instances.List(project).Do()
			if err != nil {
				return fmt.Errorf("failed to list instances: %w", err)
			}
			log.Info("Found instances", "count", len(instances.Items))

			resources := []api.AgentResource{}
			for _, instance := range instances.Items {
				// Extract region from zone (e.g. us-central1-a -> us-central1)
				region := strings.Join(strings.Split(instance.GceZone, "-")[:2], "-")

				// Add Cloud Console URL for the instance
				consoleUrl := fmt.Sprintf("https://console.cloud.google.com/sql/instances/%s?project=%s",
					instance.Name,
					project)

				host, port := getInstanceHostAndPort(instance)

				metadata := map[string]string{
					"database/type":    instance.DatabaseVersion,
					"database/region":  region,
					"database/state":   instance.State,
					"database/tier":    instance.Settings.Tier,
					"database/version": instance.DatabaseVersion,
					"database/host":    host,
					"database/port":    strconv.Itoa(port),

					"google/connection-name":   instance.ConnectionName,
					"google/availability-type": strings.ToLower(instance.Settings.AvailabilityType),
					"google/project":           project,
					"google/instance-type":     instance.InstanceType,
					"google/self-link":         instance.SelfLink,
					"google/version":           instance.DatabaseVersion,
					"google/console-url":       consoleUrl,
					"google/sla-edition":       instance.Settings.Edition,
					"google/state":             strings.ToLower(instance.State),

					"google/disk-type":                   instance.Settings.DataDiskType,
					"google/disk-size-gb":                   strconv.FormatInt(instance.Settings.DataDiskSizeGb, 10),
					"google/disk-iops":                   strconv.FormatInt(instance.Settings.DataDiskProvisionedIops, 10),
					"google/disk-provisioned-iops":       strconv.FormatInt(instance.Settings.DataDiskProvisionedIops, 10),
					"google/disk-provisioned-throughput": strconv.FormatInt(instance.Settings.DataDiskProvisionedThroughput, 10),
				}

				for _, flag := range instance.Settings.DatabaseFlags {
					metadata[fmt.Sprintf("database/parameter/%s", flag.Name)] = flag.Value
				}

				if instance.IpAddresses != nil {
					for _, ip := range instance.IpAddresses {
						metadata[fmt.Sprintf("network/%s-ip", strings.ToLower(ip.Type))] = ip.IpAddress
					}
				}

				metadata["compute/machine-type"] = instance.Settings.Tier
				metadata["compute/disk-type"] = instance.Settings.DataDiskType
				metadata["compute/disk-size"] = strconv.FormatInt(instance.Settings.DataDiskSizeGb, 10)

				if instance.Settings.AvailabilityType != "" {
					metadata["compute/availability-type"] = instance.Settings.AvailabilityType
				}

				metadata["google/project"] = project
				metadata["google/instance-type"] = instance.InstanceType
				metadata["google/self-link"] = instance.SelfLink
				metadata["google/version"] = instance.DatabaseVersion

				metadata["ctrlplane/links"] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)

				resources = append(resources, api.AgentResource{
					Version:    "ctrlplane.dev/database/v1",
					Kind:       "GoogleCloudSQL",
					Name:       instance.Name,
					Identifier: instance.SelfLink,
					Config: map[string]any{
						"name": instance.Name,
						"host": host,
						"port": port,
						"ssl":  instance.Settings.IpConfiguration != nil && instance.Settings.IpConfiguration.RequireSsl,
						"googleCloudsql": map[string]any{
							"project":                    project,
							"region":                     region,
							"version":                    instance.DatabaseVersion,
							"state":                      strings.ToLower(instance.State),
							"connectionName":             instance.ConnectionName,
							"serviceAccountEmailAddress": instance.ServiceAccountEmailAddress,
						},
					},
					Metadata: metadata,
				})
			}

			// Create or update resource provider
			if providerName == "" {
				providerName = fmt.Sprintf("google-cloudsql-%s", project)
			}

			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			workspaceId := viper.GetString("workspace")
			ctrlplaneClient, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			rp, err := api.NewResourceProvider(ctrlplaneClient, workspaceId, providerName)
			if err != nil {
				return fmt.Errorf("failed to create resource provider: %w", err)
			}

			upsertResp, err := rp.UpsertResource(ctx, resources)
			log.Info("Response from upserting resources", "status", upsertResp.Status)
			if err != nil {
				return fmt.Errorf("failed to upsert resources: %w", err)
			}

			return nil
		},
	}

	cmd.Flags().StringVarP(&providerName, "provider", "p", "", "Name of the resource provider")
	cmd.Flags().StringVarP(&project, "project", "c", "", "Google Cloud Project ID")
	cmd.MarkFlagRequired("project")

	return cmd
}

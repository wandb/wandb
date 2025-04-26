package vms

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
	"google.golang.org/api/compute/v1"
)

// NewSyncVMsCmd creates a new cobra command for syncing Google VMs
func NewSyncVMsCmd() *cobra.Command {
	var project string
	var name string

	cmd := &cobra.Command{
		Use:   "google-vms",
		Short: "Sync Google Cloud virtual machines into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Google Cloud credentials are configured via environment variables or application default credentials
			
			# Sync all VM instances from a project
			$ ctrlc sync google-vms --project my-project
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
		log.Info("Syncing Google VM instances into Ctrlplane", "project", *project)

		ctx := context.Background()

		// Initialize compute client
		computeClient, err := initComputeClient(ctx)
		if err != nil {
			return err
		}

		// List and process VM instances
		resources, err := processVMs(ctx, computeClient, *project)
		if err != nil {
			return err
		}

		// Upsert resources to Ctrlplane
		return upsertToCtrlplane(ctx, resources, project, name)
	}
}

// initComputeClient creates a new Compute Engine client
func initComputeClient(ctx context.Context) (*compute.Service, error) {
	computeClient, err := compute.NewService(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create Compute Engine client: %w", err)
	}
	return computeClient, nil
}

// processVMs lists and processes all VM instances
func processVMs(ctx context.Context, computeClient *compute.Service, project string) ([]api.AgentResource, error) {
	// Use AggregatedList to get VMs from all zones
	resp, err := computeClient.Instances.AggregatedList(project).Do()
	if err != nil {
		return nil, fmt.Errorf("failed to list VM instances: %w", err)
	}

	resources := []api.AgentResource{}
	vmCount := 0

	// Process VMs from all zones
	for zone, instanceList := range resp.Items {
		if instanceList.Instances == nil {
			continue
		}

		zoneName := getZoneFromURL(zone)
		for _, instance := range instanceList.Instances {
			resource, err := processVM(instance, project, zoneName)
			if err != nil {
				log.Error("Failed to process VM instance", "name", instance.Name, "error", err)
				continue
			}
			resources = append(resources, resource)
			vmCount++
		}
	}

	log.Info("Found VM instances", "count", vmCount)
	return resources, nil
}

// processVM handles processing of a single VM instance
func processVM(instance *compute.Instance, project string, zone string) (api.AgentResource, error) {
	metadata := initVMMetadata(instance, project, zone)

	// Extract region from zone (e.g. us-central1-a -> us-central1)
	region := ""
	if zone != "" {
		parts := strings.Split(zone, "-")
		if len(parts) >= 2 {
			region = strings.Join(parts[:2], "-")
		}
	}

	// Build console URL
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/compute/instancesDetail/zones/%s/instances/%s?project=%s",
		zone, instance.Name, project)
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)

	// Determine machine type (extract the last part of the URL)
	machineType := getResourceName(instance.MachineType)

	// Get primary internal and external IPs
	internalIP, externalIP := getInstanceIPs(instance)

	// Determine OS
	os, osVersion := getInstanceOS(instance)

	// Get network info
	networkName := ""
	if len(instance.NetworkInterfaces) > 0 && instance.NetworkInterfaces[0].Network != "" {
		networkName = getResourceName(instance.NetworkInterfaces[0].Network)
	}

	return api.AgentResource{
		Version:    "ctrlplane.dev/compute/machine/v1",
		Kind:       "GoogleComputeEngine",
		Name:       instance.Name,
		Identifier: instance.SelfLink,
		Config: map[string]any{
			"name":        instance.Name,
			"id":          strconv.FormatUint(instance.Id, 10),
			"os":          os,
			"osVersion":   osVersion,
			"cpu":         instance.CpuPlatform,
			"networkName": networkName,

			// Provider-specific implementation details
			"googleComputeEngine": map[string]any{
				"project":     project,
				"zone":        zone,
				"region":      region,
				"machineType": machineType,
				"internalIP":  internalIP,
				"externalIP":  externalIP,
			},
		},
		Metadata: metadata,
	}, nil
}

// initVMMetadata initializes the base metadata for a VM instance
func initVMMetadata(instance *compute.Instance, project string, zone string) map[string]string {
	region := ""
	if zone != "" {
		parts := strings.Split(zone, "-")
		if len(parts) >= 2 {
			region = strings.Join(parts[:2], "-")
		}
	}

	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/compute/instancesDetail/zones/%s/instances/%s?project=%s",
		zone, instance.Name, project)

	// Determine machine type
	machineType := getResourceName(instance.MachineType)

	// Get primary internal and external IPs
	internalIP, externalIP := getInstanceIPs(instance)

	// Determine OS
	os, osVersion := getInstanceOS(instance)

	metadata := map[string]string{
		"compute/type":         "vm",
		"compute/name":         instance.Name,
		"compute/id":           strconv.FormatUint(instance.Id, 10),
		"compute/zone":         zone,
		"compute/region":       region,
		"compute/status":       instance.Status,
		"compute/machine-type": machineType,
		"compute/os":           os,
		"compute/os-version":   osVersion,
		"compute/cpu-platform": instance.CpuPlatform,

		"network/internal-ip": internalIP,
		"network/external-ip": externalIP,

		"google/project":       project,
		"google/resource-type": "compute.googleapis.com/Instance",
		"google/console-url":   consoleUrl,
		"google/self-link":     instance.SelfLink,
		"google/zone":          zone,
		"google/status":        instance.Status,
	}

	// Add creation timestamp
	if instance.CreationTimestamp != "" {
		creationTime, err := time.Parse(time.RFC3339, instance.CreationTimestamp)
		if err == nil {
			metadata["compute/created"] = creationTime.Format(time.RFC3339)
		} else {
			metadata["compute/created"] = instance.CreationTimestamp
		}
	}

	// Add deletion protection status
	metadata["compute/deletion-protection"] = strconv.FormatBool(instance.DeletionProtection)

	// Add disk information
	if instance.Disks != nil {
		bootDiskSize := getBootDiskSizeGB(instance)
		if bootDiskSize > 0 {
			metadata["compute/boot-disk-size"] = strconv.FormatInt(bootDiskSize, 10)
		}
		metadata["compute/disk-count"] = strconv.Itoa(len(instance.Disks))
	}

	// Add network information
	if len(instance.NetworkInterfaces) > 0 {
		networkName := getResourceName(instance.NetworkInterfaces[0].Network)
		metadata["network/vpc"] = networkName

		if len(instance.NetworkInterfaces[0].AccessConfigs) > 0 {
			metadata["network/access-type"] = instance.NetworkInterfaces[0].AccessConfigs[0].Type
			metadata["network/tier"] = instance.NetworkInterfaces[0].AccessConfigs[0].NetworkTier
		}
	}

	// Add service account information
	if len(instance.ServiceAccounts) > 0 {
		metadata["security/service-account"] = instance.ServiceAccounts[0].Email
		if len(instance.ServiceAccounts[0].Scopes) > 0 {
			metadata["security/scopes"] = strings.Join(instance.ServiceAccounts[0].Scopes, ",")
		}
	}

	// Add tags
	if instance.Tags != nil && len(instance.Tags.Items) > 0 {
		metadata["compute/tags"] = strings.Join(instance.Tags.Items, ",")
	}

	// Add labels
	if instance.Labels != nil {
		for key, value := range instance.Labels {
			metadata[fmt.Sprintf("labels/%s", key)] = value
		}
	}

	// Add GPU information
	if len(instance.GuestAccelerators) > 0 {
		gpuTypes := []string{}
		totalGPUs := 0
		for _, gpu := range instance.GuestAccelerators {
			gpuType := getResourceName(gpu.AcceleratorType)
			gpuTypes = append(gpuTypes, gpuType)
			totalGPUs += int(gpu.AcceleratorCount)
		}
		metadata["compute/gpu-types"] = strings.Join(gpuTypes, ",")
		metadata["compute/gpu-count"] = strconv.Itoa(totalGPUs)
	}

	return metadata
}

// getInstanceIPs gets the primary internal and external IPs for a VM instance
func getInstanceIPs(instance *compute.Instance) (string, string) {
	var internalIP, externalIP string

	if len(instance.NetworkInterfaces) > 0 {
		// Get internal IP from primary network interface
		internalIP = instance.NetworkInterfaces[0].NetworkIP

		// Get external IP if available
		if len(instance.NetworkInterfaces[0].AccessConfigs) > 0 {
			externalIP = instance.NetworkInterfaces[0].AccessConfigs[0].NatIP
		}
	}

	return internalIP, externalIP
}

// getInstanceOS extracts OS information from instance metadata
func getInstanceOS(instance *compute.Instance) (string, string) {
	os := "unknown"
	osVersion := ""

	// Try to determine OS from disks
	if instance.Disks != nil {
		for _, disk := range instance.Disks {
			if disk.Boot {
				diskName := getResourceName(disk.Source)
				if strings.Contains(diskName, "debian") {
					os = "debian"
				} else if strings.Contains(diskName, "ubuntu") {
					os = "ubuntu"
				} else if strings.Contains(diskName, "rhel") {
					os = "rhel"
				} else if strings.Contains(diskName, "centos") {
					os = "centos"
				} else if strings.Contains(diskName, "windows") {
					os = "windows"
				} else if strings.Contains(diskName, "cos") {
					os = "cos"
				}

				// Try to extract version
				parts := strings.Split(diskName, "-")
				for _, part := range parts {
					if strings.Contains(part, ".") {
						osVersion = part
						break
					}
				}
				break
			}
		}
	}

	// If OS is still unknown, try to infer from metadata
	if os == "unknown" && instance.Metadata != nil {
		for _, item := range instance.Metadata.Items {
			if item.Key == "os" {
				os = *item.Value
			}
			if item.Key == "os-version" {
				osVersion = *item.Value
			}
		}
	}

	return os, osVersion
}

// getBootDiskSizeGB gets the size of the boot disk in GB
func getBootDiskSizeGB(instance *compute.Instance) int64 {
	if instance.Disks != nil {
		for _, disk := range instance.Disks {
			if disk.Boot {
				return disk.DiskSizeGb
			}
		}
	}
	return 0
}

// getZoneFromURL extracts the zone name from a URL like "zones/us-central1-a"
func getZoneFromURL(zoneURL string) string {
	parts := strings.Split(zoneURL, "/")
	if len(parts) >= 2 {
		return parts[1]
	}
	return zoneURL
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
		*name = fmt.Sprintf("google-vms-project-%s", *project)
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

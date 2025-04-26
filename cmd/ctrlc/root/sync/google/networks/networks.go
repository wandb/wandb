package networks

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

// NewSyncNetworksCmd creates a new cobra command for syncing Google Networks
func NewSyncNetworksCmd() *cobra.Command {
	var project string
	var name string

	cmd := &cobra.Command{
		Use:   "google-networks",
		Short: "Sync Google Cloud VPC networks and subnets into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Google Cloud credentials are configured via environment variables or application default credentials
			
			# Sync all VPC networks and subnets from a project
			$ ctrlc sync google-networks --project my-project
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
		log.Info("Syncing Google Network resources into Ctrlplane", "project", *project)

		ctx := context.Background()

		// Initialize compute client
		computeClient, err := initComputeClient(ctx)
		if err != nil {
			return err
		}

		// List and process networks
		networkResources, err := processNetworks(ctx, computeClient, *project)
		if err != nil {
			return err
		}

		// List and process subnets
		subnetResources, err := processSubnets(ctx, computeClient, *project)
		if err != nil {
			return err
		}

		// List and process firewall rules
		firewallResources, err := processFirewalls(ctx, computeClient, *project)
		if err != nil {
			return err
		}

		// List and process forwarding rules
		forwardingRuleResources, err := processForwardingRules(ctx, computeClient, *project)
		if err != nil {
			return err
		}

		// Combine all resources
		resources := append(networkResources, subnetResources...)
		resources = append(resources, firewallResources...)
		resources = append(resources, forwardingRuleResources...)

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

// processNetworks lists and processes all VPC networks
func processNetworks(_ context.Context, computeClient *compute.Service, project string) ([]api.AgentResource, error) {
	networks, err := computeClient.Networks.List(project).Do()
	if err != nil {
		return nil, fmt.Errorf("failed to list networks: %w", err)
	}

	log.Info("Found networks", "count", len(networks.Items))

	resources := []api.AgentResource{}
	for _, network := range networks.Items {
		// Count subnets for this network
		subnetCount := 0
		subnets, err := computeClient.Subnetworks.AggregatedList(project).Filter("network=" + network.SelfLink).Do()
		if err == nil && subnets.Items != nil {
			for _, subnetList := range subnets.Items {
				if subnetList.Subnetworks != nil {
					subnetCount += len(subnetList.Subnetworks)
				}
			}
		}

		resource, err := processNetwork(network, project, subnetCount)
		if err != nil {
			log.Error("Failed to process network", "name", network.Name, "error", err)
			continue
		}
		resources = append(resources, resource)
	}

	return resources, nil
}

// processNetwork handles processing of a single VPC network
func processNetwork(network *compute.Network, project string, subnetCount int) (api.AgentResource, error) {
	metadata := initNetworkMetadata(network, project, subnetCount)

	// Build console URL
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/networking/networks/details/%s?project=%s",
		network.Name, project)
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)

	// Determine subnet mode
	subnetMode := "CUSTOM"
	if network.AutoCreateSubnetworks {
		subnetMode = "AUTO"
	}

	// Create peering info for metadata
	if network.Peerings != nil {
		for i, peering := range network.Peerings {
			metadata[fmt.Sprintf("network/peering/%d/name", i)] = peering.Name
			metadata[fmt.Sprintf("network/peering/%d/network", i)] = getResourceName(peering.Network)
			metadata[fmt.Sprintf("network/peering/%d/state", i)] = peering.State
			metadata[fmt.Sprintf("network/peering/%d/auto-create-routes", i)] = strconv.FormatBool(peering.AutoCreateRoutes)
		}
		metadata["network/peering-count"] = strconv.Itoa(len(network.Peerings))
	}

	return api.AgentResource{
		Version:    "ctrlplane.dev/network/v1",
		Kind:       "GoogleNetwork",
		Name:       network.Name,
		Identifier: network.SelfLink,
		Config: map[string]any{
			// Common cross-provider options
			"name": network.Name,
			"type": "vpc",
			"id":   strconv.FormatUint(network.Id, 10),
			"mtu":  network.Mtu,

			// Provider-specific implementation details
			"googleNetwork": map[string]any{
				"project":           project,
				"selfLink":          network.SelfLink,
				"subnetMode":        subnetMode,
				"autoCreateSubnets": network.AutoCreateSubnetworks,
				"subnetCount":       subnetCount,
				"routingMode":       network.RoutingConfig.RoutingMode,
			},
		},
		Metadata: metadata,
	}, nil
}

// initNetworkMetadata initializes the base metadata for a network
func initNetworkMetadata(network *compute.Network, project string, subnetCount int) map[string]string {
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/networking/networks/details/%s?project=%s",
		network.Name, project)

	// Determine subnet mode
	subnetMode := "custom"
	if network.AutoCreateSubnetworks {
		subnetMode = "auto"
	}

	metadata := map[string]string{
		"network/type":         "vpc",
		"network/name":         network.Name,
		"network/subnet-mode":  subnetMode,
		"network/subnet-count": strconv.Itoa(subnetCount),
		"network/id":           strconv.FormatUint(network.Id, 10),
		"network/mtu":          strconv.FormatInt(network.Mtu, 10),

		"google/self-link":     network.SelfLink,
		"google/project":       project,
		"google/resource-type": "compute.googleapis.com/Network",
		"google/console-url":   consoleUrl,
		"google/id":            strconv.FormatUint(network.Id, 10),
	}

	// Add creation timestamp
	if network.CreationTimestamp != "" {
		creationTime, err := time.Parse(time.RFC3339, network.CreationTimestamp)
		if err == nil {
			metadata["network/created"] = creationTime.Format(time.RFC3339)
		} else {
			metadata["network/created"] = network.CreationTimestamp
		}
	}

	// Add routing configuration
	if network.RoutingConfig != nil && network.RoutingConfig.RoutingMode != "" {
		metadata["network/routing-mode"] = network.RoutingConfig.RoutingMode
	}

	return metadata
}

// processSubnets lists and processes all subnetworks
func processSubnets(_ context.Context, computeClient *compute.Service, project string) ([]api.AgentResource, error) {
	// Use AggregatedList to get subnets from all regions
	resp, err := computeClient.Subnetworks.AggregatedList(project).Do()
	if err != nil {
		return nil, fmt.Errorf("failed to list subnetworks: %w", err)
	}

	resources := []api.AgentResource{}
	subnetCount := 0

	// Process subnets from all regions
	for region, subnetList := range resp.Items {
		if subnetList.Subnetworks == nil {
			continue
		}

		regionName := getRegionFromURL(region)
		for _, subnet := range subnetList.Subnetworks {
			resource, err := processSubnet(subnet, project, regionName)
			if err != nil {
				log.Error("Failed to process subnet", "name", subnet.Name, "error", err)
				continue
			}
			resources = append(resources, resource)
			subnetCount++
		}
	}

	log.Info("Found subnets", "count", subnetCount)
	return resources, nil
}

// processSubnet handles processing of a single subnet
func processSubnet(subnet *compute.Subnetwork, project string, region string) (api.AgentResource, error) {
	metadata := initSubnetMetadata(subnet, project, region)

	// Build console URL
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/networking/subnetworks/details/%s/%s?project=%s",
		region, subnet.Name, project)
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)

	// Extract network name from self link
	networkName := getResourceName(subnet.Network)

	return api.AgentResource{
		Version:    "ctrlplane.dev/network/v1",
		Kind:       "GoogleSubnet",
		Name:       subnet.Name,
		Identifier: subnet.SelfLink,
		Config: map[string]any{
			// Common cross-provider options
			"name":        subnet.Name,
			"provider":    "google",
			"type":        "subnet",
			"cidr":        subnet.IpCidrRange,
			"region":      region,
			"id":          strconv.FormatUint(subnet.Id, 10),
			"gateway":     subnet.GatewayAddress,
			"networkName": networkName,

			// Provider-specific implementation details
			"googleSubnet": map[string]any{
				"project":               project,
				"purpose":               subnet.Purpose,
				"role":                  subnet.Role,
				"privateIpGoogleAccess": subnet.PrivateIpGoogleAccess,
				"network":               subnet.Network,
				"stackType":             subnet.StackType,
				"ipv6AccessType":        subnet.Ipv6AccessType,
				"enableFlowLogs":        subnet.EnableFlowLogs,
				"secondaryIpRanges":     subnet.SecondaryIpRanges,
			},
		},
		Metadata: metadata,
	}, nil
}

// initSubnetMetadata initializes the base metadata for a subnet
func initSubnetMetadata(subnet *compute.Subnetwork, project string, region string) map[string]string {
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/networking/subnetworks/details/%s/%s?project=%s",
		region, subnet.Name, project)

	// Extract network name from self link
	networkName := getResourceName(subnet.Network)

	metadata := map[string]string{
		"network/type":           "subnet",
		"network/name":           subnet.Name,
		"network/vpc":            networkName,
		"network/region":         region,
		"network/cidr":           subnet.IpCidrRange,
		"network/gateway":        subnet.GatewayAddress,
		"network/private-access": strconv.FormatBool(subnet.PrivateIpGoogleAccess),

		"google/project":       project,
		"google/resource-type": "compute.googleapis.com/Subnetwork",
		"google/console-url":   consoleUrl,
		"google/region":        region,
		"google/id":            strconv.FormatUint(subnet.Id, 10),
	}

	// Add creation timestamp
	if subnet.CreationTimestamp != "" {
		creationTime, err := time.Parse(time.RFC3339, subnet.CreationTimestamp)
		if err == nil {
			metadata["network/created"] = creationTime.Format(time.RFC3339)
		} else {
			metadata["network/created"] = subnet.CreationTimestamp
		}
	}

	// Add purpose and role if set
	if subnet.Purpose != "" {
		metadata["network/purpose"] = subnet.Purpose
		if subnet.Role != "" {
			metadata["network/role"] = subnet.Role
		}
	}

	// Add secondary IP ranges if present
	if subnet.SecondaryIpRanges != nil {
		for i, secondaryRange := range subnet.SecondaryIpRanges {
			metadata[fmt.Sprintf("network/secondary-range/%d/name", i)] = secondaryRange.RangeName
			metadata[fmt.Sprintf("network/secondary-range/%d/cidr", i)] = secondaryRange.IpCidrRange
		}
		metadata["network/secondary-range-count"] = strconv.Itoa(len(subnet.SecondaryIpRanges))
	}

	// Add IP version details
	if subnet.StackType != "" {
		metadata["network/stack-type"] = subnet.StackType
	}
	if subnet.Ipv6AccessType != "" {
		metadata["network/ipv6-access-type"] = subnet.Ipv6AccessType
	}
	if subnet.InternalIpv6Prefix != "" {
		metadata["network/internal-ipv6-prefix"] = subnet.InternalIpv6Prefix
	}
	if subnet.ExternalIpv6Prefix != "" {
		metadata["network/external-ipv6-prefix"] = subnet.ExternalIpv6Prefix
	}

	// Add flow logs status
	if subnet.EnableFlowLogs {
		metadata["network/flow-logs"] = "enabled"
	} else {
		metadata["network/flow-logs"] = "disabled"
	}

	return metadata
}

// processFirewalls lists and processes all firewall rules
func processFirewalls(ctx context.Context, computeClient *compute.Service, project string) ([]api.AgentResource, error) {
	firewalls, err := computeClient.Firewalls.List(project).Do()
	if err != nil {
		return nil, fmt.Errorf("failed to list firewalls: %w", err)
	}

	log.Info("Found firewall rules", "count", len(firewalls.Items))

	resources := []api.AgentResource{}
	for _, firewall := range firewalls.Items {
		resource, err := processFirewall(firewall, project)
		if err != nil {
			log.Error("Failed to process firewall rule", "name", firewall.Name, "error", err)
			continue
		}
		resources = append(resources, resource)
	}

	return resources, nil
}

// processFirewall handles processing of a single firewall rule
func processFirewall(firewall *compute.Firewall, project string) (api.AgentResource, error) {
	metadata := initFirewallMetadata(firewall, project)

	// Build console URL for the network (since firewalls don't have direct URLs)
	networkName := getResourceName(firewall.Network)
	consoleUrl := fmt.Sprintf("https://console.cloud.google.com/networking/networks/details/%s/firewall?project=%s",
		networkName, project)
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)

	return api.AgentResource{
		Version:    "ctrlplane.dev/network/v1",
		Kind:       "GoogleFirewall",
		Name:       firewall.Name,
		Identifier: firewall.SelfLink,
		Config: map[string]any{
			// Common cross-provider options
			"name":        firewall.Name,
			"id":          strconv.FormatUint(firewall.Id, 10),
			"direction":   firewall.Direction,
			"priority":    firewall.Priority,
			"enabled":     firewall.Disabled,
			"networkName": networkName,

			// Core firewall rule information that crosses providers
			"sourceRanges":      firewall.SourceRanges,
			"destinationRanges": firewall.DestinationRanges,
			"rules": map[string]any{
				"allowed": firewall.Allowed,
				"denied":  firewall.Denied,
			},

			// Provider-specific implementation details
			"googleFirewall": map[string]any{
				"project":               project,
				"network":               firewall.Network,
				"targetTags":            firewall.TargetTags,
				"sourceTags":            firewall.SourceTags,
				"sourceServiceAccounts": firewall.SourceServiceAccounts,
				"targetServiceAccounts": firewall.TargetServiceAccounts,
			},
		},
		Metadata: metadata,
	}, nil
}

// initFirewallMetadata initializes the base metadata for a firewall rule
func initFirewallMetadata(firewall *compute.Firewall, project string) map[string]string {
	networkName := getResourceName(firewall.Network)

	// Determine if this is an ingress or egress rule
	direction := "INGRESS"
	if firewall.Direction != "" {
		direction = firewall.Direction
	}

	// Determine if this is an allow or deny rule
	ruleType := "allow"
	if len(firewall.Denied) > 0 {
		ruleType = "deny"
	}

	metadata := map[string]string{
		"firewall/network":   networkName,
		"firewall/name":      firewall.Name,
		"firewall/direction": direction,
		"firewall/priority":  strconv.FormatInt(firewall.Priority, 10),
		"firewall/disabled":  strconv.FormatBool(firewall.Disabled),
		"firewall/rule-type": ruleType,

		"google/self-link":     firewall.SelfLink,
		"google/project":       project,
		"google/resource-type": "compute.googleapis.com/Firewall",
		"google/id":            strconv.FormatUint(firewall.Id, 10),
	}

	// Add creation timestamp
	if firewall.CreationTimestamp != "" {
		creationTime, err := time.Parse(time.RFC3339, firewall.CreationTimestamp)
		if err == nil {
			metadata["network/created"] = creationTime.Format(time.RFC3339)
		} else {
			metadata["network/created"] = firewall.CreationTimestamp
		}
	}

	// Add rule status
	if firewall.Disabled {
		metadata["firewall/status"] = "disabled"
	} else {
		metadata["firewall/status"] = "enabled"
	}

	// Process allow rules
	if len(firewall.Allowed) > 0 {
		protocols := []string{}
		for i, rule := range firewall.Allowed {
			protocols = append(protocols, rule.IPProtocol)
			metadata[fmt.Sprintf("firewall/allow/%d/protocol", i)] = rule.IPProtocol

			if len(rule.Ports) > 0 {
				metadata[fmt.Sprintf("firewall/allow/%d/ports", i)] = strings.Join(rule.Ports, ",")
			}
		}
		metadata["firewall/allow-protocols"] = strings.Join(protocols, ",")
		metadata["firewall/allow-count"] = strconv.Itoa(len(firewall.Allowed))
	}

	// Process deny rules
	if len(firewall.Denied) > 0 {
		protocols := []string{}
		for i, rule := range firewall.Denied {
			protocols = append(protocols, rule.IPProtocol)
			metadata[fmt.Sprintf("firewall/deny/%d/protocol", i)] = rule.IPProtocol

			if len(rule.Ports) > 0 {
				metadata[fmt.Sprintf("firewall/deny/%d/ports", i)] = strings.Join(rule.Ports, ",")
			}
		}
		metadata["firewall/deny-protocols"] = strings.Join(protocols, ",")
		metadata["firewall/deny-count"] = strconv.Itoa(len(firewall.Denied))
	}

	// Add sources and targets
	if len(firewall.SourceRanges) > 0 {
		metadata["firewall/source-ranges"] = strings.Join(firewall.SourceRanges, ",")
	}
	if len(firewall.DestinationRanges) > 0 {
		metadata["firewall/destination-ranges"] = strings.Join(firewall.DestinationRanges, ",")
	}
	if len(firewall.SourceTags) > 0 {
		metadata["firewall/source-tags"] = strings.Join(firewall.SourceTags, ",")
	}
	if len(firewall.TargetTags) > 0 {
		metadata["firewall/target-tags"] = strings.Join(firewall.TargetTags, ",")
	}
	if len(firewall.SourceServiceAccounts) > 0 {
		metadata["firewall/source-service-accounts"] = strings.Join(firewall.SourceServiceAccounts, ",")
	}
	if len(firewall.TargetServiceAccounts) > 0 {
		metadata["firewall/target-service-accounts"] = strings.Join(firewall.TargetServiceAccounts, ",")
	}

	return metadata
}

// processForwardingRules lists and processes all forwarding rules (load balancers)
func processForwardingRules(_ context.Context, computeClient *compute.Service, project string) ([]api.AgentResource, error) {
	// Use AggregatedList to get forwarding rules from all regions
	resp, err := computeClient.ForwardingRules.AggregatedList(project).Do()
	if err != nil {
		return nil, fmt.Errorf("failed to list forwarding rules: %w", err)
	}

	resources := []api.AgentResource{}
	ruleCount := 0

	// Process forwarding rules from all regions
	for region, ruleList := range resp.Items {
		if ruleList.ForwardingRules == nil {
			continue
		}

		regionName := getRegionFromURL(region)
		for _, rule := range ruleList.ForwardingRules {
			resource, err := processForwardingRule(rule, project, regionName)
			if err != nil {
				log.Error("Failed to process forwarding rule", "name", rule.Name, "error", err)
				continue
			}
			resources = append(resources, resource)
			ruleCount++
		}
	}

	log.Info("Found forwarding rules", "count", ruleCount)
	return resources, nil
}

// processForwardingRule handles processing of a single forwarding rule
func processForwardingRule(rule *compute.ForwardingRule, project string, region string) (api.AgentResource, error) {
	metadata := initForwardingRuleMetadata(rule, project, region)

	// Build console URL
	var consoleUrl string
	if rule.LoadBalancingScheme == "INTERNAL" {
		consoleUrl = fmt.Sprintf("https://console.cloud.google.com/net-services/loadbalancing/details/internal/%s/%s?project=%s",
			region, rule.Name, project)
	} else {
		consoleUrl = fmt.Sprintf("https://console.cloud.google.com/net-services/loadbalancing/details/external/%s/%s?project=%s",
			region, rule.Name, project)
	}
	metadata["ctrlplane/links"] = fmt.Sprintf("{ \"Google Cloud Console\": \"%s\" }", consoleUrl)

	// Extract network name from self link if present
	networkName := ""
	if rule.Network != "" {
		networkName = getResourceName(rule.Network)
	}

	return api.AgentResource{
		Version:    "ctrlplane.dev/network/forwarding-rule/v1",
		Kind:       "GoogleForwardingRule",
		Name:       rule.Name,
		Identifier: rule.SelfLink,
		Config: map[string]any{
			// Common cross-provider options
			"name":             rule.Name,
			"type":             "loadbalancer",
			"id":               strconv.FormatUint(rule.Id, 10),
			"region":           region,
			"ip":               rule.IPAddress,
			"protocol":         rule.IPProtocol,
			"ports":            rule.Ports,
			"portRange":        rule.PortRange,
			"networkName":      networkName,
			"loadBalancerType": rule.LoadBalancingScheme,

			// Provider-specific implementation details
			"googleForwardingRule": map[string]any{
				"project":        project,
				"target":         rule.Target,
				"backendService": rule.BackendService,
				"serviceLabel":   rule.ServiceLabel,
				"serviceName":    rule.ServiceName,
				"networkTier":    rule.NetworkTier,
				"subnetwork":     rule.Subnetwork,
				"network":        rule.Network,
			},
		},
		Metadata: metadata,
	}, nil
}

// initForwardingRuleMetadata initializes the base metadata for a forwarding rule
func initForwardingRuleMetadata(rule *compute.ForwardingRule, project string, region string) map[string]string {
	// Determine type of load balancer
	loadBalancerType := "external"
	if rule.LoadBalancingScheme == "INTERNAL" {
		loadBalancerType = "internal"
	}

	// Extract network name from self link if present
	networkName := ""
	if rule.Network != "" {
		networkName = getResourceName(rule.Network)
	}

	// Extract subnetwork name from self link if present
	subnetName := ""
	if rule.Subnetwork != "" {
		subnetName = getResourceName(rule.Subnetwork)
	}

	// Extract target name from self link if present
	targetName := ""
	if rule.Target != "" {
		targetName = getResourceName(rule.Target)
	}

	// Extract backend service name from self link if present
	backendServiceName := ""
	if rule.BackendService != "" {
		backendServiceName = getResourceName(rule.BackendService)
	}

	metadata := map[string]string{
		"network/type":        "forwarding-rule",
		"network/name":        rule.Name,
		"network/region":      region,
		"network/ip-address":  rule.IPAddress,
		"network/ip-protocol": rule.IPProtocol,
		"network/lb-type":     loadBalancerType,
		"network/lb-scheme":   rule.LoadBalancingScheme,

		"google/project":       project,
		"google/resource-type": "compute.googleapis.com/ForwardingRule",
		"google/console-url": fmt.Sprintf("https://console.cloud.google.com/net-services/loadbalancing/details/%s/%s/%s?project=%s",
			loadBalancerType, region, rule.Name, project),
		"google/region": region,
		"google/id":     strconv.FormatUint(rule.Id, 10),
	}

	// Add creation timestamp
	if rule.CreationTimestamp != "" {
		creationTime, err := time.Parse(time.RFC3339, rule.CreationTimestamp)
		if err == nil {
			metadata["network/created"] = creationTime.Format(time.RFC3339)
		} else {
			metadata["network/created"] = rule.CreationTimestamp
		}
	}

	// Add network details if present
	if networkName != "" {
		metadata["network/vpc"] = networkName
	}
	if subnetName != "" {
		metadata["network/subnet"] = subnetName
	}

	// Add port details
	if rule.PortRange != "" {
		metadata["network/port-range"] = rule.PortRange
	}
	if len(rule.Ports) > 0 {
		metadata["network/ports"] = strings.Join(rule.Ports, ",")
	}

	// Add target details
	if targetName != "" {
		metadata["network/target"] = targetName
	}
	if backendServiceName != "" {
		metadata["network/backend-service"] = backendServiceName
	}

	// Add service details
	if rule.ServiceLabel != "" {
		metadata["network/service-label"] = rule.ServiceLabel
	}
	if rule.ServiceName != "" {
		metadata["network/service-name"] = rule.ServiceName
	}

	// Add network tier if present
	if rule.NetworkTier != "" {
		metadata["network/tier"] = rule.NetworkTier
	}

	return metadata
}

// getRegionFromURL extracts the region name from a URL like "regions/us-central1"
func getRegionFromURL(regionURL string) string {
	parts := strings.Split(regionURL, "/")
	if len(parts) >= 2 {
		return parts[1]
	}
	return regionURL
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
		*name = fmt.Sprintf("google-networks-project-%s", *project)
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

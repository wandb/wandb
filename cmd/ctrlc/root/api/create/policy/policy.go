package policy

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewCreatePolicyCmd() *cobra.Command {
	var name string
	var description string
	var priority float32
	var enabled bool
	var deploymentTargetSelector string
	var environmentTargetSelector string
	var resourceTargetSelector string
	var denyWindows string
	var versionAnyApprovals string
	var versionUserApprovals string
	var versionRoleApprovals string
	var deploymentVersionSelector string

	cmd := &cobra.Command{
		Use:   "policy [flags]",
		Short: "Create a new policy",
		Long:  `Create a new policy with specified parameters`,
		Example: heredoc.Doc(`
			# Create a new policy
			$ ctrlc create policy --name my-policy

			# Create a new policy with deployment selector
			$ ctrlc create policy --name my-policy --deployment-selector '{"type": "production"}'

			# Create a new policy with environment selector
			$ ctrlc create policy --name my-policy --environment-selector '{"name": "prod"}'

			# Create a new policy with deny windows
			$ ctrlc create policy --name my-policy --deny-windows '[{"timeZone": "UTC", "rrule": {"freq": "WEEKLY", "byday": ["SA", "SU"]}}]'

			# Create a new policy with version approvals
			$ ctrlc create policy --name my-policy --version-any-approvals '{"requiredApprovalsCount": 2}' --version-user-approvals '[{"userId": "user1"}, {"userId": "user2"}]' --version-role-approvals '[{"roleId": "role1", "requiredApprovalsCount": 1}]'
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			workspaceId := viper.GetString("workspace")

			if workspaceId == "" {
				return fmt.Errorf("workspace is required")
			}

			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			// Parse selectors from JSON strings
			var deploymentSelector *map[string]interface{}
			if deploymentTargetSelector != "" {
				var parsedSelector map[string]interface{}
				if err := json.Unmarshal([]byte(deploymentTargetSelector), &parsedSelector); err != nil {
					return fmt.Errorf("invalid deployment target selector JSON: %w", err)
				}
				deploymentSelector = &parsedSelector
			}

			var environmentSelector *map[string]interface{}
			if environmentTargetSelector != "" {
				var parsedSelector map[string]interface{}
				if err := json.Unmarshal([]byte(environmentTargetSelector), &parsedSelector); err != nil {
					return fmt.Errorf("invalid environment target selector JSON: %w", err)
				}
				environmentSelector = &parsedSelector
			}

			var resourceSelector *map[string]interface{}
			if resourceTargetSelector != "" {
				var parsedSelector map[string]interface{}
				if err := json.Unmarshal([]byte(resourceTargetSelector), &parsedSelector); err != nil {
					return fmt.Errorf("invalid resource target selector JSON: %w", err)
				}
				resourceSelector = &parsedSelector
			}

			// Parse deny windows
			var parsedDenyWindows []struct {
				Dtend    *time.Time              `json:"dtend,omitempty"`
				Rrule    *map[string]interface{} `json:"rrule,omitempty"`
				TimeZone string                  `json:"timeZone"`
			}
			if denyWindows != "" {
				if err := json.Unmarshal([]byte(denyWindows), &parsedDenyWindows); err != nil {
					return fmt.Errorf("invalid deny windows JSON: %w", err)
				}
			}

			// Parse version any approvals
			var parsedVersionAnyApprovals *[]struct {
				RequiredApprovalsCount *float32 `json:"requiredApprovalsCount,omitempty"`
			}
			if versionAnyApprovals != "" {
				var approvals []struct {
					RequiredApprovalsCount *float32 `json:"requiredApprovalsCount,omitempty"`
				}
				if err := json.Unmarshal([]byte(versionAnyApprovals), &approvals); err != nil {
					return fmt.Errorf("invalid version any approvals JSON: %w", err)
				}
				parsedVersionAnyApprovals = &approvals
			}

			// Parse version user approvals
			var parsedVersionUserApprovals []api.VersionUserApproval
			if versionUserApprovals != "" {
				if err := json.Unmarshal([]byte(versionUserApprovals), &parsedVersionUserApprovals); err != nil {
					return fmt.Errorf("invalid version user approvals JSON: %w", err)
				}
			} else {
				parsedVersionUserApprovals = []api.VersionUserApproval{}
			}

			// Parse version role approvals
			var parsedVersionRoleApprovals []struct {
				RequiredApprovalsCount *float32 `json:"requiredApprovalsCount,omitempty"`
				RoleId                 *string  `json:"roleId,omitempty"`
			}
			if versionRoleApprovals != "" {
				if err := json.Unmarshal([]byte(versionRoleApprovals), &parsedVersionRoleApprovals); err != nil {
					return fmt.Errorf("invalid version role approvals JSON: %w", err)
				}
			} else {
				parsedVersionRoleApprovals = []struct {
					RequiredApprovalsCount *float32 `json:"requiredApprovalsCount,omitempty"`
					RoleId                 *string  `json:"roleId,omitempty"`
				}{}
			}

			// Parse deployment version selector
			var parsedDeploymentVersionSelector *api.DeploymentVersionSelector
			if deploymentVersionSelector != "" {
				var selector map[string]interface{}

				if err := json.Unmarshal([]byte(deploymentVersionSelector), &selector); err != nil {
					return fmt.Errorf("invalid deployment version selector JSON: %w", err)
				}

				parsedDeploymentVersionSelector = &api.DeploymentVersionSelector{
					DeploymentVersionSelector: selector,
					Name:                      name,
				}
			}

			// Create policy request
			body := api.CreatePolicyJSONRequestBody{
				Name:        name,
				WorkspaceId: workspaceId,
				Description: &description,
				Priority:    &priority,
				Enabled:     &enabled,
				Targets: []api.PolicyTarget{
					{
						DeploymentSelector:  deploymentSelector,
						EnvironmentSelector: environmentSelector,
						ResourceSelector:    resourceSelector,
					},
				},
				DenyWindows:               parsedDenyWindows,
				DeploymentVersionSelector: parsedDeploymentVersionSelector,
				VersionAnyApprovals:       parsedVersionAnyApprovals,
				VersionUserApprovals:      parsedVersionUserApprovals,
				VersionRoleApprovals:      parsedVersionRoleApprovals,
			}

			resp, err := client.CreatePolicy(cmd.Context(), body)
			if err != nil {
				return fmt.Errorf("failed to create policy: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	// Add flags
	cmd.Flags().String("workspace", "", "ID of the workspace (required)")
	cmd.Flags().StringVarP(&name, "name", "n", "", "Name of the policy (required)")
	cmd.Flags().StringVarP(&description, "description", "d", "", "Description of the policy")
	cmd.Flags().Float32VarP(&priority, "priority", "p", 0, "Priority of the policy (default: 0)")
	cmd.Flags().BoolVarP(&enabled, "enabled", "e", true, "Whether the policy is enabled (default: true)")
	cmd.Flags().StringVar(&deploymentTargetSelector, "deployment-selector", "", "JSON string for deployment target selector")
	cmd.Flags().StringVar(&environmentTargetSelector, "environment-selector", "", "JSON string for environment target selector")
	cmd.Flags().StringVar(&resourceTargetSelector, "resource-selector", "", "JSON string for resource target selector")
	cmd.Flags().StringVar(&denyWindows, "deny-windows", "", "JSON string for deny windows")
	cmd.Flags().StringVar(&versionAnyApprovals, "version-any-approvals", "", "JSON string for version any approvals")
	cmd.Flags().StringVar(&versionUserApprovals, "version-user-approvals", "", "JSON string for version user approvals")
	cmd.Flags().StringVar(&versionRoleApprovals, "version-role-approvals", "", "JSON string for version role approvals")
	cmd.Flags().StringVar(&deploymentVersionSelector, "version-selector", "", "JSON string for version selector")

	// Mark required flags
	cmd.MarkFlagRequired("name")

	return cmd
}

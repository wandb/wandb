package policy

import (
	"encoding/json"
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewUpsertPolicyCmd() *cobra.Command {
	var name string
	var description string
	var priority float32
	var enabled bool
	var deploymentTargetSelector string
	var environmentTargetSelector string
	var resourceTargetSelector string
	var deploymentVersionSelector string

	cmd := &cobra.Command{
		Use:   "policy [flags]",
		Short: "Upsert a policy",
		Long:  `Upsert a policy with specified parameters`,
		Example: heredoc.Doc(`
			# Upsert a new policy
			$ ctrlc api upsert policy --name my-policy

			# Upsert a policy with deployment selector
			$ ctrlc api upsert policy --name my-policy --deployment-selector '{"type": "production"}'

			# Upsert a policy with environment selector
			$ ctrlc api upsert policy --name my-policy --environment-selector '{"name": "prod"}'

			# Upsert a policy with deny windows
			$ ctrlc api upsert policy --name my-policy --deny-windows '[{"timeZone": "UTC", "rrule": {"freq": "WEEKLY", "byday": ["SA", "SU"]}}]'

			# Upsert a policy with version approvals
			$ ctrlc api upsert policy --name my-policy --version-any-approvals '{"requiredApprovalsCount": 2}' --version-user-approvals '[{"userId": "user1"}, {"userId": "user2"}]' --version-role-approvals '[{"roleId": "role1", "requiredApprovalsCount": 1}]'
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
			var deploymentSelector *map[string]any
			if deploymentTargetSelector != "" {
				var parsedSelector map[string]any
				if err := json.Unmarshal([]byte(deploymentTargetSelector), &parsedSelector); err != nil {
					return fmt.Errorf("invalid deployment target selector JSON: %w", err)
				}
				deploymentSelector = &parsedSelector
			}

			var environmentSelector *map[string]any
			if environmentTargetSelector != "" {
				var parsedSelector map[string]any
				if err := json.Unmarshal([]byte(environmentTargetSelector), &parsedSelector); err != nil {
					return fmt.Errorf("invalid environment target selector JSON: %w", err)
				}
				environmentSelector = &parsedSelector
			}

			var resourceSelector *map[string]any
			if resourceTargetSelector != "" {
				var parsedSelector map[string]any
				if err := json.Unmarshal([]byte(resourceTargetSelector), &parsedSelector); err != nil {
					return fmt.Errorf("invalid resource target selector JSON: %w", err)
				}
				resourceSelector = &parsedSelector
			}

			// Parse deployment version selector
			var parsedDeploymentVersionSelector *api.DeploymentVersionSelector
			if deploymentVersionSelector != "" {
				var selector map[string]any

				if err := json.Unmarshal([]byte(deploymentVersionSelector), &selector); err != nil {
					return fmt.Errorf("invalid deployment version selector JSON: %w", err)
				}

				parsedDeploymentVersionSelector = &api.DeploymentVersionSelector{
					DeploymentVersionSelector: selector,
					Name:                      name,
				}
			}

			// Create policy request
			body := api.UpsertPolicyJSONRequestBody{
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
				DeploymentVersionSelector: parsedDeploymentVersionSelector,
			}

			resp, err := client.UpsertPolicy(cmd.Context(), body)
			if err != nil {
				return fmt.Errorf("failed to create policy: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	// Add flags
	cmd.Flags().StringVarP(&name, "name", "n", "", "Name of the policy (required)")
	cmd.Flags().StringVarP(&description, "description", "d", "", "Description of the policy")
	cmd.Flags().Float32VarP(&priority, "priority", "p", 0, "Priority of the policy (default: 0)")
	cmd.Flags().BoolVarP(&enabled, "enabled", "e", true, "Whether the policy is enabled (default: true)")
	cmd.Flags().StringVar(&deploymentTargetSelector, "deployment-selector", "", "JSON string for deployment target selector")
	cmd.Flags().StringVar(&environmentTargetSelector, "environment-selector", "", "JSON string for environment target selector")
	cmd.Flags().StringVar(&resourceTargetSelector, "resource-selector", "", "JSON string for resource target selector")

	cmd.Flags().StringVar(&deploymentVersionSelector, "version-selector", "", "JSON string for version selector")

	// Mark required flags
	cmd.MarkFlagRequired("name")

	return cmd
}

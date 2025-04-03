package deploymentversionchannel

import (
	"encoding/json"
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewCreateDeploymentVersionChannelCmd() *cobra.Command {
	var name string
	var deploymentID string
	var description string
	var selector string

	cmd := &cobra.Command{
		Use:   "deployment-version-channel [flags]",
		Short: "Create a new deployment version channel",
		Long:  `Create a new deployment version channel with the specified name and configuration.`,
		Example: heredoc.Doc(`
			# Create a new deployment version channel
			$ ctrlc create deployment-version-channel --name my-version-channel --deployment 1234567890

			# Create a new deployment version channel with selector
			$ ctrlc create deployment-version-channel --name my-version-channel --deployment 1234567890 --selector '{"type":"tag","operator":"equals","value":"v1.0.0"}'
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			versionSelector := make(map[string]interface{})
			if selector != "" {
				if err := json.Unmarshal([]byte(selector), &versionSelector); err != nil {
					return fmt.Errorf("failed to parse version selector JSON: %w", err)
				}
			}

			resp, err := client.CreateDeploymentVersionChannel(cmd.Context(), api.CreateDeploymentVersionChannelJSONRequestBody{
				Name:            name,
				DeploymentId:    deploymentID,
				Description:     &description,
				VersionSelector: versionSelector,
			})
			if err != nil {
				return fmt.Errorf("failed to create deployment version channel: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	// Add flags
	cmd.Flags().StringVar(&name, "name", "", "Name of the deployment version channel (required)")
	cmd.Flags().StringVar(&deploymentID, "deployment", "", "ID of the deployment (required)")
	cmd.Flags().StringVar(&selector, "selector", "", "JSON string containing version selector criteria")
	cmd.Flags().StringVar(&description, "description", "", "Description of the deployment version channel")
	cmd.MarkFlagRequired("name")
	cmd.MarkFlagRequired("deployment")

	return cmd
}

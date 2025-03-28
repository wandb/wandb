package releasechannel

import (
	"encoding/json"
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewCreateReleaseChannelCmd() *cobra.Command {
	var name string
	var deploymentID string
	var description string
	var selector string

	cmd := &cobra.Command{
		Use:   "release-channel [flags]",
		Short: "Create a new release channel",
		Long:  `Create a new release channel with the specified name and configuration.`,
		Example: heredoc.Doc(`
			# Create a new release channel
			$ ctrlc create release-channel --name my-release-channel

			# Create a new release channel using Go template syntax
			$ ctrlc create release-channel --name my-release-channel --template='{{.status.phase}}'
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			releaseSelector := make(map[string]interface{})
			if selector != "" {
				if err := json.Unmarshal([]byte(selector), &releaseSelector); err != nil {
					return fmt.Errorf("failed to parse release selector JSON: %w", err)
				}
			}

			resp, err := client.CreateReleaseChannel(cmd.Context(), api.CreateReleaseChannelJSONRequestBody{
				Name:            name,
				DeploymentId:    deploymentID,
				Description:     &description,
				ReleaseSelector: releaseSelector,
			})
			if err != nil {
				return fmt.Errorf("failed to create release channel: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	// Add flags
	cmd.Flags().StringVar(&name, "name", "", "Name of the release channel (required)")
	cmd.Flags().StringVar(&deploymentID, "deployment", "", "ID of the deployment (required)")
	cmd.Flags().StringVar(&selector, "selector", "", "JSON string containing release selector criteria")
	cmd.Flags().StringVar(&description, "description", "", "Description of the release channel")
	cmd.MarkFlagRequired("name")
	cmd.MarkFlagRequired("deployment-id")

	return cmd
}

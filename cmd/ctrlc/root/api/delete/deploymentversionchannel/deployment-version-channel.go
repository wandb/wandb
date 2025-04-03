package deploymentversionchannel

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewDeleteDeploymentVersionChannelCmd() *cobra.Command {
	var deploymentID string
	var name string

	cmd := &cobra.Command{
		Use:   "deployment-version-channel [flags]",
		Short: "Delete a deployment version channel",
		Long:  `Delete a deployment version channel by specifying a deployment ID and a name.`,
		Example: heredoc.Doc(`
			$ ctrlc delete deployment-version-channel --deployment 123e4567-e89b-12d3-a456-426614174000 --name mychannel
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			if deploymentID == "" || name == "" {
				return fmt.Errorf("deployment and name are required")
			}

			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}
			resp, err := client.DeleteDeploymentVersionChannel(cmd.Context(), deploymentID, name)
			if err != nil {
				return fmt.Errorf("failed to delete deployment version channel: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVar(&deploymentID, "deployment", "", "Deployment ID")
	cmd.Flags().StringVar(&name, "name", "", "Deployment version channel name")

	return cmd
}

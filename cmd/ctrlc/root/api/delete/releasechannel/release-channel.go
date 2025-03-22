package releasechannel

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewDeleteReleaseChannelCmd() *cobra.Command {
	var deploymentId string
	var name string

	cmd := &cobra.Command{
		Use:   "release-channel [flags]",
		Short: "Delete a release channel",
		Long:  `Delete a release channel by specifying a deployment ID and a name.`,
		Example: heredoc.Doc(`
			$ ctrlc delete release-channel --deployment 123e4567-e89b-12d3-a456-426614174000 --name mychannel
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			if deploymentId == "" || name == "" {
				return fmt.Errorf("deployment and name are required")
			}

			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}
			resp, err := client.DeleteReleaseChannel(cmd.Context(), deploymentId, name)
			if err != nil {
				return fmt.Errorf("failed to delete release channel: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVar(&deploymentId, "deployment", "", "Deployment ID")
	cmd.Flags().StringVar(&name, "name", "", "Release channel name")

	return cmd
}

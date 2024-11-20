package environment

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewDeleteEnvironmentCmd() *cobra.Command {
	var environmentId string
	

	cmd := &cobra.Command{
		Use:   "environment [flags]",
		Short: "Delete an environment",
		Long:  `Delete an environment by specifying either an ID or both a workspace and an identifier.`,
		Example: heredoc.Doc(`
            # Delete a resource by ID
            $ ctrlc delete resource --id 123e4567-e89b-12d3-a456-426614174000

            # Delete a resource by workspace and identifier
            $ ctrlc delete resource --workspace 123e4567-e89b-12d3-a456-426614174000 --identifier myidentifier

            # Delete a resource using Go template syntax
            $ ctrlc delete environment --id 123e4567-e89b-12d3-a456-426614174000 --template='{{.id}}'
        `),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to delete environment API client: %w", err)
			}
			resp, err := client.DeleteEnvironment(cmd.Context(), environmentId)
			if err != nil {
				return fmt.Errorf("failed to delete environment by ID: %w", err)
			}
			return cliutil.HandleOutput(cmd, resp)
		},
	}

	// Add flags
	cmd.Flags().StringVar(&environmentId, "id", "", "ID of the environment")
	cmd.MarkFlagRequired("id")

	return cmd
}

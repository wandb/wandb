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
	var systemId string
	var name string

	cmd := &cobra.Command{
		Use:   "environment [flags]",
		Short: "Delete an environment",
		Long:  `Delete an environment by specifying either an ID or both a workspace and an identifier.`,
		Example: heredoc.Doc(`
            # Delete a environment by ID
            $ ctrlc delete environment --id 123e4567-e89b-12d3-a456-426614174000

            # Delete a environment by system and name
            $ ctrlc delete environment --system 123e4567-e89b-12d3-a456-426614174000 --name myenv

            # Delete a environment using Go template syntax
            $ ctrlc delete environment --id 123e4567-e89b-12d3-a456-426614174000 --template='{{.id}}'
        `),
		PreRunE: func(cmd *cobra.Command, args []string) error {
			if environmentId == "" && (systemId == "" || name == "") {
				return fmt.Errorf("either --id or both --system and --name must be provided")
			}
			if environmentId != "" && (systemId != "" || name != "") {
				return fmt.Errorf("--id and --system/--name are mutually exclusive")
			}
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to delete environment API client: %w", err)
			}

			if environmentId != "" {
				resp, err := client.DeleteEnvironment(cmd.Context(), environmentId)
				if err != nil {
					return fmt.Errorf("failed to delete environment by ID: %w", err)
				}
				return cliutil.HandleResponseOutput(cmd, resp)
			}

			resp, err := client.DeleteEnvironmentByName(cmd.Context(), systemId, name)
			if err != nil {
				return fmt.Errorf("failed to delete environment by system and name: %w", err)
			}
			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVar(&environmentId, "id", "", "ID of the environment")
	cmd.Flags().StringVar(&systemId, "system", "", "ID of the system")
	cmd.Flags().StringVar(&name, "name", "", "Name of the environment")

	return cmd
}

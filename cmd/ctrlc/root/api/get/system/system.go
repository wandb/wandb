package system

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/google/uuid"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewGetSystemCmd() *cobra.Command {
	var system string

	cmd := &cobra.Command{
		Use:   "system [flags]",
		Short: "Get a system",
		Long:  `Get a system by specifying an ID.`,
		Example: heredoc.Doc(`
            # Get a system by ID
            $ ctrlc get system --id 123e4567-e89b-12d3-a456-426614174000

            # Get a system using Go template syntax
            $ ctrlc get system --id 123e4567-e89b-12d3-a456-426614174000 --template='{{.id}}'
        `),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			systemId, err := uuid.Parse(system)
			if err != nil {
				return fmt.Errorf("invalid system ID: %w", err)
			}

			resp, err := client.GetSystem(cmd.Context(), systemId)
			if err != nil {
				return fmt.Errorf("failed to get system by ID: %w", err)
			}
			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVarP(&system, "system", "s", "", "ID of the system")
	cmd.MarkFlagRequired("system")

	return cmd
}

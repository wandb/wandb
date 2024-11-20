package system

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewGetSystemCmd() *cobra.Command {
	var systemId string

	cmd := &cobra.Command{
		Use:   "resource [flags]",
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

			resp, err := client.GetSystem(cmd.Context(), systemId)
			if err != nil {
				return fmt.Errorf("failed to get system by ID: %w", err)
			}
			return cliutil.HandleOutput(cmd, resp)
		},
	}

	// Add flags
	cmd.Flags().StringVar(&systemId, "id", "", "ID of the system")
	cmd.MarkFlagRequired("id")

	return cmd
}

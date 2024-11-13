package target

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewTargetCmd() *cobra.Command {
	var targetId string

	cmd := &cobra.Command{
		Use:   "target [flags]",
		Short: "Get a target",
		Long:  `Get a target with the specified name and configuration.`,
		Example: heredoc.Doc(`
			# Get a target
			$ ctrlc get target --name my-target

			# Get a target using Go template syntax
			$ ctrlc get target --name my-target --template='{{.id}}'
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			resp, err := client.GetTarget(cmd.Context(), targetId)
			if err != nil {
				return fmt.Errorf("failed to get target: %w", err)
			}

			return cliutil.HandleOutput(cmd, resp)
		},
	}

	// Add flags
	cmd.Flags().StringVar(&targetId, "id", "", "ID of the target (required)")
	cmd.MarkFlagRequired("id")

	return cmd
}

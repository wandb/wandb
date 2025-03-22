package resource

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewGetResourceCmd() *cobra.Command {
	var resourceId string
	var workspace string
	var identifier string

	cmd := &cobra.Command{
		Use:   "resource [flags]",
		Short: "Get a resource",
		Long:  `Get a resource by specifying either an ID or both a workspace and an identifier.`,
		Example: heredoc.Doc(`
            # Get a resource by ID
            $ ctrlc get resource --id 123e4567-e89b-12d3-a456-426614174000

            # Get a resource by workspace and identifier
            $ ctrlc get resource --workspace myworkspace --identifier myidentifier

            # Get a resource using Go template syntax
            $ ctrlc get resource --id 123e4567-e89b-12d3-a456-426614174000 --template='{{.id}}'
        `),
		RunE: func(cmd *cobra.Command, args []string) error {
			if resourceId == "" && (workspace == "" || identifier == "") {
				return fmt.Errorf("either --id or both --workspace and --identifier must be provided")
			}

			if resourceId != "" && (workspace != "" || identifier != "") {
				return fmt.Errorf("--id and --workspace/--identifier are mutually exclusive")
			}

			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			if resourceId != "" {
				resp, err := client.GetResource(cmd.Context(), resourceId)
				if err != nil {
					return fmt.Errorf("failed to get resource by ID: %w", err)
				}
				return cliutil.HandleResponseOutput(cmd, resp)
			}

			resp, err := client.GetResourceByIdentifier(cmd.Context(), workspace, identifier)
			if err != nil {
				return fmt.Errorf("failed to get resource by workspace and identifier: %w", err)
			}
			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	// Add flags
	cmd.Flags().StringVar(&resourceId, "id", "", "ID of the target resource")
	cmd.Flags().StringVar(&workspace, "workspace", "", "Workspace of the target resource")
	cmd.Flags().StringVar(&identifier, "identifier", "", "Identifier of the target resource")

	return cmd
}

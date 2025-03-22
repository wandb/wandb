package workspace

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/google/uuid"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewGetWorkspaceCmd() *cobra.Command {
	var workspaceId string
	var workspaceSlug string

	cmd := &cobra.Command{
		Use:   "workspace [flags]",
		Short: "Get a workspace",
		Long:  `Get a workspace by specifying either an ID or a slug.`,
		Example: heredoc.Doc(`
            # Get a workspace by ID
            $ ctrlc api get workspace --id 123e4567-e89b-12d3-a456-426614174000

            # Get a workspace by slug
            $ ctrlc api get workspace --slug myworkspace 

            # Get a workspace using Go template syntax
            $ ctrlc api get workspace --id 123e4567-e89b-12d3-a456-426614174000 --template='{{.id}}'
        `),
		RunE: func(cmd *cobra.Command, args []string) error {
			if workspaceId == "" && workspaceSlug == "" {
				return fmt.Errorf("either --id or --slug must be provided")
			}

			if workspaceId != "" && workspaceSlug != "" {
				return fmt.Errorf("--id and --slug are mutually exclusive")
			}

			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			if workspaceId != "" {
				wsId, err := uuid.Parse(workspaceId)
				if err != nil {
					return fmt.Errorf("invalid workspace ID: %w", err)
				}

				resp, err := client.GetWorkspace(cmd.Context(), wsId)
				if err != nil {
					return fmt.Errorf("failed to get workspace by ID: %w", err)
				}
				return cliutil.HandleResponseOutput(cmd, resp)
			}

			resp, err := client.GetWorkspaceBySlug(cmd.Context(), workspaceSlug)
			if err != nil {
				return fmt.Errorf("failed to get workspace by slug: %w", err)
			}
			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVar(&workspaceId, "id", "", "ID of the workspace")
	cmd.Flags().StringVar(&workspaceSlug, "slug", "", "Slug of the workspace")

	return cmd
}

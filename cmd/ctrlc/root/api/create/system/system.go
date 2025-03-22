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

func getSystemName(name, slug string) string {
	if name != "" {
		return name
	}
	return slug
}

func NewCreateSystemCmd() *cobra.Command {
	var name string
	var slug string
	var description string
	var workspace string
	cmd := &cobra.Command{
		Use:   "system [flags]",
		Short: "Create a new system",
		Long:  "Create a new system with the specified name and configuration.",
		Example: heredoc.Doc(`
			# Create a new system
			$ ctrlc create system --name my-system --slug my-system --workspace 00000000-0000-0000-0000-000000000000
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			workspaceId, err := uuid.Parse(workspace)
			if err != nil {
				return fmt.Errorf("invalid workspace ID: %w", err)
			}

			body := api.CreateSystemJSONRequestBody{
				Slug:        slug,
				WorkspaceId: workspaceId,
				Name:        getSystemName(name, slug),
			}

			if description != "" {
				body.Description = &description
			}

			resp, err := client.CreateSystem(cmd.Context(), body)
			if err != nil {
				return fmt.Errorf("failed to create system: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVarP(&name, "name", "n", "", "Name of the system (will default to slug if not provided)")
	cmd.Flags().StringVarP(&slug, "slug", "l", "", "Slug of the system (required)")
	cmd.Flags().StringVarP(&description, "description", "d", "", "Description of the system")
	cmd.Flags().StringVarP(&workspace, "workspace", "w", "", "ID of the workspace (required)")

	cmd.MarkFlagRequired("slug")
	cmd.MarkFlagRequired("workspace")

	return cmd
}

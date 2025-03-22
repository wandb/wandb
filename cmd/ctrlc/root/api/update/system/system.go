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

func NewUpdateSystemCmd() *cobra.Command {
	var system string
	var name string
	var slug string
	var description string
	var workspace string

	cmd := &cobra.Command{
		Use:   "system [flags]",
		Short: "Update a system",
		Long:  "Update a system with the specified name and configuration.",
		Example: heredoc.Doc(`
			# Update a system
			$ ctrlc update system --system 00000000-0000-0000-0000-000000000000 \
				 --name my-system --slug my-system --workspace 00000000-0000-0000-0000-000000000000
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			if system == "" {
				return fmt.Errorf("system ID is required")
			}

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

			body := api.UpdateSystemJSONRequestBody{}
			if name != "" {
				body.Name = &name
			}
			if slug != "" {
				body.Slug = &slug
			}
			if description != "" {
				body.Description = &description
			}
			if workspace != "" {
				workspaceId, err := uuid.Parse(workspace)
				if err != nil {
					return fmt.Errorf("invalid workspace ID: %w", err)
				}
				body.WorkspaceId = &workspaceId
			}

			resp, err := client.UpdateSystem(cmd.Context(), systemId, body)
			if err != nil {
				return fmt.Errorf("failed to update system: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVarP(&system, "system", "s", "", "ID of the system (required)")
	cmd.Flags().StringVarP(&name, "name", "n", "", "Name of the system")
	cmd.Flags().StringVarP(&slug, "slug", "l", "", "Slug of the system")
	cmd.Flags().StringVarP(&description, "description", "d", "", "Description of the system")
	cmd.Flags().StringVarP(&workspace, "workspace", "w", "", "ID of the workspace")

	cmd.MarkFlagRequired("system")

	return cmd
}

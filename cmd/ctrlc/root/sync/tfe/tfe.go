package tfe

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/hashicorp/go-tfe"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func validateArgs(organization, workspace string) error {
	if organization == "" && workspace == "" {
		return fmt.Errorf("either organization or workspace must be provided")
	}
	if organization != "" && workspace != "" {
		return fmt.Errorf("only one of organization or workspace can be provided")
	}
	return nil
}

func NewSyncTfeCmd() *cobra.Command {
	var ctrlplaneWorkspaceId string
	var organization string
	var workspace string

	cmd := &cobra.Command{
		Use:   "tfe",
		Short: "Sync TFE resources into Ctrlplane",
		Example: heredoc.Doc(`
			# Sync all workspaces in an organization
			$ ctrlc sync tfe --organization my-org --ctrlplane-workspace-id 1234567890

			# Sync a specific workspace
			$ ctrlc sync tfe --workspace 1234567890 --ctrlplane-workspace-id 1234567890
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")

			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			if err := validateArgs(organization, workspace); err != nil {
				return fmt.Errorf("invalid arguments: %w", err)
			}

			tfeClient, err := tfe.NewClient(tfe.DefaultConfig())
			if err != nil {
				return fmt.Errorf("failed to create TFE client: %w", err)
			}

			return nil
		},
	}

	return cmd
}

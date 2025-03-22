package terraform

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/google/uuid"
	"github.com/hashicorp/go-tfe"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewSyncTerraformCmd() *cobra.Command {
	var organization string

	cmd := &cobra.Command{
		Use:   "terraform",
		Short: "Sync Terraform resources into Ctrlplane",
		Example: heredoc.Doc(`
			# To set the Terraform token, add TFE_TOKEN to your environment variables.
			export TFE_TOKEN=...

			# To set the Terraform address, add TFE_ADDRESS to your environment variables.
			export TFE_ADDRESS=... else the default address (https://app.terraform.io) is used.

			# Sync all workspaces in an organization
			$ ctrlc sync terraform --organization my-org --workspace 2a7c5560-75c9-4dbe-be74-04ee33bf8188
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			log.Info("Syncing Terraform resources into Ctrlplane")

			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			workspaceId := viper.GetString("workspace")
			ctx := cmd.Context()

			if organization == "" {
				return fmt.Errorf("organization is required")
			}

			if _, err := uuid.Parse(workspaceId); err != nil {
				return fmt.Errorf("invalid workspace ID: %w", err)
			}

			ctrlplaneClient, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			terraformClient, err := tfe.NewClient(tfe.DefaultConfig())
			if err != nil {
				return fmt.Errorf("failed to create Terraform client: %w", err)
			}

			providerName := fmt.Sprintf("tf-%s", organization)
			resp, err := ctrlplaneClient.UpsertResourceProviderWithResponse(ctx, workspaceId, providerName)
			if err != nil {
				return fmt.Errorf("failed to upsert resource provider: %w", err)
			}

			if resp.JSON200 == nil {
				return fmt.Errorf("failed to upsert resource provider: %s", resp.Body)
			}

			providerId := resp.JSON200.Id
			fmt.Println("Provider ID:", providerId)
			workspaces, err := getWorkspacesInOrg(cmd.Context(), terraformClient, organization)
			if err != nil {
				return fmt.Errorf("failed to get workspaces in organization: %w", err)
			}

			resources := []struct {
				Config     map[string]interface{} `json:"config"`
				Identifier string                 `json:"identifier"`
				Kind       string                 `json:"kind"`
				Metadata   map[string]string      `json:"metadata"`
				Name       string                 `json:"name"`
				Version    string                 `json:"version"`
			}{}

			for _, workspace := range workspaces {
				resource := struct {
					Config     map[string]interface{} `json:"config"`
					Identifier string                 `json:"identifier"`
					Kind       string                 `json:"kind"`
					Metadata   map[string]string      `json:"metadata"`
					Name       string                 `json:"name"`
					Version    string                 `json:"version"`
				}{
					Version:    workspace.Version,
					Identifier: workspace.Identifier,
					Metadata:   workspace.Metadata,
					Name:       workspace.Name,
					Kind:       workspace.Kind,
					Config:     workspace.Config,
				}
				resources = append(resources, resource)
			}

			upsertResp, err := ctrlplaneClient.SetResourceProvidersResources(ctx, providerId, api.SetResourceProvidersResourcesJSONRequestBody{
				Resources: resources,
			})
			if err != nil {
				return fmt.Errorf("failed to upsert resources: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, upsertResp)
		},
	}

	cmd.Flags().StringVarP(&organization, "organization", "o", "", "Terraform organization name")

	return cmd
}

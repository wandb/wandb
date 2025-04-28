package resource

import (
	"encoding/json"
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/google/uuid"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewUpsertResourceCmd() *cobra.Command {
	var name string
	var identifier string
	var kind string
	var version string
	var metadata map[string]string
	var configArray map[string]string
	var links map[string]string
	var variables map[string]string

	cmd := &cobra.Command{
		Use:   "resource [flags]",
		Short: "Upsert a resource",
		Long:  `Upsert a resource with the specified version and configuration.`,
		Example: heredoc.Doc(`
			# Upsert a resource
			$ ctrlc upsert resource --version v1.0.0

			# Upsert a resource using Go template syntax
			$ ctrlc upsert resource --version v1.0.0 --template='{{.status.phase}}'
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			workspaceId := viper.GetString("workspace")

			if workspaceId == "" {
				return fmt.Errorf("workspace is required")
			}

			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			config := cliutil.ConvertConfigArrayToNestedMap(configArray)
			if len(links) > 0 {
				linksJSON, err := json.Marshal(links)
				if err != nil {
					return fmt.Errorf("failed to marshal links: %w", err)
				}
				metadata["ctrlplane/links"] = string(linksJSON)
			}

			variablesRequest := &[]api.Variable{}
			for k, v := range variables {
				sensitive := false
				vv := api.Variable{}
				dvv := api.DirectVariable_Value{}
				dvv.SetString(v)
				vv.FromDirectVariable(api.DirectVariable{
					Key:       k,
					Sensitive: &sensitive,
					Value:     dvv,
				})

				*variablesRequest = append(*variablesRequest, vv)
			}

			// Extrat into vars
			resp, err := client.UpsertResource(cmd.Context(), api.UpsertResourceJSONRequestBody{
				Config:      config,
				Identifier:  identifier,
				Kind:        kind,
				Metadata:    &metadata,
				Name:        name,
				Variables:   variablesRequest,
				Version:     version,
				WorkspaceId: uuid.Must(uuid.Parse(workspaceId)),
			})

			if err != nil {
				return fmt.Errorf("failed to create resource: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	// Add flags
	cmd.Flags().StringVar(&name, "name", "", "Name of the resource (required)")
	cmd.Flags().StringVar(&identifier, "identifier", "", "Identifier of the resource (required)")
	cmd.Flags().StringVar(&kind, "kind", "", "Kind of the resource (required)")
	cmd.Flags().StringVar(&version, "version", "", "Version of the resource (required)")

	cmd.Flags().StringToStringVar(&variables, "var", make(map[string]string), "Variable key-value pairs (can be specified multiple times)")
	cmd.Flags().StringToStringVar(&metadata, "metadata", make(map[string]string), "Metadata key-value pairs (e.g. --metadata key=value)")
	cmd.Flags().StringToStringVar(&configArray, "config", make(map[string]string), "Config key-value pairs with nested values (can be specified multiple times)")
	cmd.Flags().StringToStringVar(&links, "link", make(map[string]string), "Links key-value pairs (can be specified multiple times)")

	cmd.MarkFlagRequired("version")
	cmd.MarkFlagRequired("name")
	cmd.MarkFlagRequired("identifier")
	cmd.MarkFlagRequired("kind")

	return cmd
}

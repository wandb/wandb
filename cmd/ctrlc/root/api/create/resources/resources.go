package resources

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/google/uuid"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewResourcesCmd() *cobra.Command {
	var workspaceID string
	var name string
	var identifier string
	var kind string
	var version string
	var metadata map[string]string
	var configArray map[string]string

	cmd := &cobra.Command{
		Use:   "resources [flags]",
		Short: "Create a new resources",
		Long:  `Create a new resources with the specified version and configuration.`,
		Example: heredoc.Doc(`
			# Create a new resource
			$ ctrlc create resources --version v1.0.0

			# Create a new resource using Go template syntax
			$ ctrlc create resources --version v1.0.0 --template='{{.status.phase}}'
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			// Convert configArray into a nested map[string]interface{}
			config := make(map[string]interface{})
			for path, value := range configArray {
				// Split path into segments
				segments := strings.Split(path, ".")

				// Start at the root map
				current := config

				// Navigate through segments
				for i, segment := range segments {
					if i == len(segments)-1 {
						// Last segment - try to convert string to number or boolean if possible
						if num, err := strconv.ParseFloat(value, 64); err == nil {
							current[segment] = num
						} else if value == "true" {
							current[segment] = true
						} else if value == "false" {
							current[segment] = false
						} else {
							current[segment] = value
						}
					} else {
						// Create nested map if it doesn't exist
						if _, exists := current[segment]; !exists {
							current[segment] = make(map[string]interface{})
						}
						// Move to next level
						current = current[segment].(map[string]interface{})
					}
				}
			}

			// Extrat into vars
			resp, err := client.UpsertTargets(cmd.Context(), api.UpsertTargetsJSONRequestBody{
				Targets: []struct {
					Config     map[string]interface{} `json:"config"`
					Identifier string                 `json:"identifier"`
					Kind       string                 `json:"kind"`
					Metadata   *map[string]string     `json:"metadata,omitempty"`
					Name       string                 `json:"name"`
					Variables  *[]struct {
						Key       string                                            `json:"key"`
						Sensitive *bool                                             `json:"sensitive,omitempty"`
						Value     api.UpsertTargetsJSONBody_Targets_Variables_Value `json:"value"`
					} `json:"variables,omitempty"`
					Version string `json:"version"`
				}{
					{
						Version:    version,
						Identifier: identifier,
						Metadata:   &metadata,
						Name:       name,
						Kind:       kind,
						Config:     config,
					},
				},

				WorkspaceId: uuid.Must(uuid.Parse(workspaceID)),
			})

			if err != nil {
				return fmt.Errorf("failed to create resource: %w", err)
			}

			return cliutil.HandleOutput(cmd, resp)
		},
	}

	// Add flags
	cmd.Flags().StringVar(&workspaceID, "workspace", "", "ID of the workspace (required)")
	cmd.Flags().StringVar(&name, "name", "", "Name of the resource (required)")
	cmd.Flags().StringVar(&identifier, "identifier", "", "Identifier of the resource (required)")
	cmd.Flags().StringVar(&kind, "kind", "", "Kind of the resource (required)")
	cmd.Flags().StringVar(&version, "version", "", "Version of the resource (required)")
	cmd.Flags().StringToStringVar(&metadata, "metadata", make(map[string]string), "Metadata key-value pairs (e.g. --metadata key=value)")
	cmd.Flags().StringToStringVar(&configArray, "config", make(map[string]string), "Config key-value pairs with nested values (can be specified multiple times)")

	cmd.MarkFlagRequired("version")
	cmd.MarkFlagRequired("workspace")
	cmd.MarkFlagRequired("name")
	cmd.MarkFlagRequired("identifier")
	cmd.MarkFlagRequired("kind")

	return cmd
}

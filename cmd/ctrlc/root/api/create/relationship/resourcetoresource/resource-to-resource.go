package resourcetoresource

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/google/uuid"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewCreateRelationshipCmd() *cobra.Command {
	var fromIdentifier string
	var toIdentifier string
	var workspaceId string
	var relationshipType string

	cmd := &cobra.Command{
		Use:   "resource-to-resource [flags]",
		Short: "Create a new relationship between two resources",
		Long:  `Create a new relationship between two resources.`,
		Example: heredoc.Doc(`
			# Create a new relationship between two resources
			$ ctrlc create relationship resource-to-resource --from my-resource --to another-resource --workspace-id 123e4567-e89b-12d3-a456-426614174000 --type depends_on
		`),
		PreRunE: func(cmd *cobra.Command, args []string) error {
			if workspaceId == "" {
				log.Error("workspace is required")
				return fmt.Errorf("workspace-id is required")
			}

			if fromIdentifier == "" {
				log.Error("from is required")
				return fmt.Errorf("from is required")
			}

			if toIdentifier == "" {
				log.Error("to is required")
				return fmt.Errorf("to is required")
			}

			if relationshipType == "" {
				log.Error("type is required")
				return fmt.Errorf("type is required")
			}

			if relationshipType != "associated_with" && relationshipType != "depends_on" {
				log.Error("type must be either 'associated_with' or 'depends_on', got %s", relationshipType)
				return fmt.Errorf("type must be either 'associated_with' or 'depends_on', got %s", relationshipType)
			}

			if fromIdentifier == toIdentifier {
				log.Error("from and to cannot be the same")
				return fmt.Errorf("from and to cannot be the same")
			}

			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")

			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				log.Error("failed to create relationship API client", "error", err)
				return fmt.Errorf("failed to create relationship API client: %w", err)
			}

			workspaceIdUUID, err := uuid.Parse(workspaceId)
			if err != nil {
				log.Error("failed to parse workspace id", "error", err)
				return fmt.Errorf("failed to parse workspace id: %w", err)
			}

			resp, err := client.CreateResourceToResourceRelationship(cmd.Context(), api.CreateResourceToResourceRelationshipJSONRequestBody{
				FromIdentifier: fromIdentifier,
				ToIdentifier:   toIdentifier,
				WorkspaceId:    workspaceIdUUID,
				Type:           relationshipType,
			})
			if err != nil {
				log.Error("failed to create resource to resource relationship", "error", err)
				return fmt.Errorf("failed to create resource to resource relationship: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVarP(&fromIdentifier, "from", "f", "", "Identifier of the source resource (required)")
	cmd.Flags().StringVarP(&toIdentifier, "to", "t", "", "Identifier of the target resource (required)")
	cmd.Flags().StringVarP(&workspaceId, "workspace", "w", "", "ID of the workspace (required)")
	cmd.Flags().StringVarP(&relationshipType, "type", "T", "", "Type of the relationship (must be 'associated_with' or 'depends_on') (required)")

	cmd.MarkFlagRequired("from")
	cmd.MarkFlagRequired("to")
	cmd.MarkFlagRequired("workspace")
	cmd.MarkFlagRequired("type")

	return cmd
}

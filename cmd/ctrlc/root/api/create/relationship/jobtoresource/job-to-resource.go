package jobtoresource

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/google/uuid"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewCreateRelationshipCmd() *cobra.Command {
	var jobId string
	var resourceIdentifier string

	cmd := &cobra.Command{
		Use:   "job-to-resource [flags]",
		Short: "Create a new relationship between a job and a resource",
		Long:  `Create a new relationship between a job and a resource.`,
		Example: heredoc.Doc(`
			# Create a new relationship between a job and a resource
			$ ctrlc create relationship job-to-resource --job-id 123e4567-e89b-12d3-a456-426614174000 --resource-identifier my-resource
		`),
		PreRunE: func(cmd *cobra.Command, args []string) error {
			if jobId == "" {
				return fmt.Errorf("job-id is required")
			}

			if resourceIdentifier == "" {
				return fmt.Errorf("resource-identifier is required")
			}

			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")

			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create relationship API client: %w", err)
			}

			jobIdUUID, err := uuid.Parse(jobId)
			if err != nil {
				return fmt.Errorf("failed to parse job-id: %w", err)
			}

			resp, err := client.CreateJobToResourceRelationship(cmd.Context(), api.CreateJobToResourceRelationshipJSONRequestBody{
				JobId:              jobIdUUID,
				ResourceIdentifier: resourceIdentifier,
			})
			if err != nil {
				return fmt.Errorf("failed to create job-to-resource relationship: %w", err)
			}

			return cliutil.HandleOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVarP(&jobId, "job", "j", "", "ID of the job (required)")
	cmd.Flags().StringVarP(&resourceIdentifier, "resource", "r", "", "Identifier of the resource (required)")

	cmd.MarkFlagRequired("job")
	cmd.MarkFlagRequired("resource")

	return cmd
}

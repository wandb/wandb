package relationship

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/spf13/cobra"
)

func NewCreateRelationshipCmd() *cobra.Command {
	var fromId string
	var toId string
	var fromType string
	var toType string

	cmd := &cobra.Command{
		Use:   "relationship [flags]",
		Short: "Create a new relationship",
		Long:  `Create a new relationship between two entities.`,
		Example: heredoc.Doc(`

		`),
		PreRunE: func(cmd *cobra.Command, args []string) error {
			if fromType != "deployment" && fromType != "resource" {
				return fmt.Errorf("from-type must be either 'deployment' or 'resource', got %s", fromType)
			}

			if toType != "deployment" && toType != "resource" {
				return fmt.Errorf("to-type must be either 'deployment' or 'resource', got %s", toType)
			}

			if fromId == toId && fromType == toType {
				return fmt.Errorf("from and to cannot be the same")
			}

			if fromType == "deployment" && toType == "deployment" {
				return fmt.Errorf("cannot create relationship between two deployments")
			}

			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			// apiURL := viper.GetString("url")
			// apiKey := viper.GetString("api-key")

			// return cliutil.HandleOutput(cmd, response)
			return nil
		},
	}

	// Add flags
	cmd.Flags().StringVarP(&fromId, "from", "f", "", "ID of the source resource (required)")
	cmd.Flags().StringVarP(&toId, "to", "t", "", "ID of the target resource (required)")
	cmd.Flags().StringVarP(&fromType, "from-type", "F", "", "Type of the source resource (must be 'deployment' or 'resource') (required)")
	cmd.Flags().StringVarP(&toType, "to-type", "T", "", "Type of the target resource (must be 'deployment' or 'resource') (required)")

	cmd.MarkFlagRequired("from")
	cmd.MarkFlagRequired("to")
	cmd.MarkFlagRequired("from-type")
	cmd.MarkFlagRequired("to-type")

	return cmd
}

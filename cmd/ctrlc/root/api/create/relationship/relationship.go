package relationship

import (
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/relationship/jobtoresource"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/relationship/resourcetoresource"
	"github.com/spf13/cobra"
)

func NewRelationshipCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "relationship <command>",
		Short: "Create a relationship",
		Long:  `Create a relationship between two entities.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	cmd.AddCommand(resourcetoresource.NewCreateRelationshipCmd())
	cmd.AddCommand(jobtoresource.NewCreateRelationshipCmd())

	return cmd
}

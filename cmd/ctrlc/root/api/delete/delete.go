package delete

import (
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/delete/resource"
	"github.com/spf13/cobra"
)

func NewDeleteCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "delete <command>",
		Short: "Delete resources",
		Long:  `Commands for deleting resources.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	cmd.AddCommand(resource.NewDeleteResourceCmd())

	return cmd
}

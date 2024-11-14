package upsert

import (
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/upsert/resource"
	"github.com/spf13/cobra"
)

func NewUpsertCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "upsert <command>",
		Short: "Upsert resources",
		Long:  `Commands for upserting resources.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	cmd.AddCommand(resource.NewUpsertResourceCmd())

	return cmd
}

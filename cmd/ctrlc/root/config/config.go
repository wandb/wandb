package config

import (
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/config/set"
	"github.com/spf13/cobra"
)

func NewConfigCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "config <command>",
		Short: "Configuration commands",
		Long:  `Commands for managing the CLI configuration.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	cmd.AddCommand(set.NewSetCmd())

	return cmd
}

package create

import (
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/environment"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/release"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/releasechannel"
	"github.com/spf13/cobra"
)

func NewCreateCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "create <command>",
		Short: "Create resources",
		Long:  `Commands for creating resources.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	cmd.AddCommand(release.NewReleaseCmd())
	cmd.AddCommand(releasechannel.NewReleaseChannelCmd())
	cmd.AddCommand(environment.NewEnvironmentCmd())

	return cmd
}

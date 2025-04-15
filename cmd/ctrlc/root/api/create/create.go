package create

import (
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/deploymentversion"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/deploymentversionchannel"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/environment"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/relationship"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/release"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/releasechannel"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create/system"
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

	cmd.AddCommand(releasechannel.NewCreateReleaseChannelCmd())
	cmd.AddCommand(deploymentversionchannel.NewCreateDeploymentVersionChannelCmd())
	cmd.AddCommand(deploymentversion.NewCreateDeploymentVersionCmd())
	cmd.AddCommand(environment.NewCreateEnvironmentCmd())
	cmd.AddCommand(relationship.NewRelationshipCmd())
	cmd.AddCommand(release.NewCreateReleaseCmd())
	cmd.AddCommand(system.NewCreateSystemCmd())

	return cmd
}

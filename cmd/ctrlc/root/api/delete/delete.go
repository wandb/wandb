package delete

import (
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/delete/deploymentversionchannel"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/delete/environment"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/delete/policy"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/delete/releasechannel"
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
	cmd.AddCommand(environment.NewDeleteEnvironmentCmd())
	cmd.AddCommand(releasechannel.NewDeleteReleaseChannelCmd())
	cmd.AddCommand(deploymentversionchannel.NewDeleteDeploymentVersionChannelCmd())
	cmd.AddCommand(policy.NewDeletePolicyCmd())
	return cmd
}

package agent

import (
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/agent/run"
	"github.com/spf13/cobra"
)

func NewAgentCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "agent <command>",
		Short: "Agent management commands",
		Long:  `Commands for managing the agent that can be connected to from Ctrlplane.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	cmd.AddCommand(run.NewAgentRunCmd())

	return cmd
}

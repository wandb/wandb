package run

import (
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/run/exec"
	"github.com/spf13/cobra"
)

func NewRunCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "run",
		Short: "Runners listen for jobs and execute them.",
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	cmd.AddCommand(exec.NewRunExecCmd())

	return cmd
}

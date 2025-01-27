package run

import (
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/run/exec"
	"github.com/ctrlplanedev/cli/internal/cliutil"
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

	cmd.AddCommand(cliutil.AddIntervalSupport(exec.NewRunExecCmd(), ""))

	return cmd
}

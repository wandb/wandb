package root

import (
	"github.com/MakeNowJust/heredoc/v2"

	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/agent"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/apply"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/config"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/run"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/version"
	"github.com/spf13/cobra"
)

func NewRootCmd() *cobra.Command {
	var logLevel string

	cmd := &cobra.Command{
		Use:   "ctrlc <command> <subcommand> [subcommand] [flags]",
		Short: "Ctrlplane CLI",
		Long:  `Configure and manage your deployment environments remotely.`,
		Example: heredoc.Doc(`
			$ ctrlc agent run
			$ ctrlc connect <agent-name>
		`),
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			switch logLevel {
			case "debug":
				log.SetLevel(log.DebugLevel)
			case "info":
				log.SetLevel(log.InfoLevel)
			case "warn":
				log.SetLevel(log.WarnLevel)
			case "error":
				log.SetLevel(log.ErrorLevel)
			}
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	cmd.PersistentFlags().StringVar(&logLevel, "log-level", "info", "Set the logging level (debug, info, warn, error)")

	cmd.AddCommand(agent.NewAgentCmd())
	cmd.AddCommand(api.NewAPICmd())
	cmd.AddCommand(config.NewConfigCmd())
	cmd.AddCommand(sync.NewSyncCmd())
	cmd.AddCommand(run.NewRunCmd())
	cmd.AddCommand(version.NewVersionCmd())
	cmd.AddCommand(apply.NewApplyCmd())

	return cmd
}

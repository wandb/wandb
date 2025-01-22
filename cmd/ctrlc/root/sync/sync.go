package sync

import (
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/tailscale"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/terraform"
	"github.com/spf13/cobra"
)

func AddIntervalSupport(cmd *cobra.Command) *cobra.Command {
	var interval string

	run := cmd.RunE

	cmd.RunE = func(cmd *cobra.Command, args []string) error {
		if interval != "" {
			log.Info("Running command on interval", "interval", interval)
			duration, err := time.ParseDuration(interval)
			if err != nil {
				log.Error("Failed to parse interval duration", "error", err)
				return err
			}

			iteration := uint64(1)
			for {
				log.Info(">>> Starting iteration", "number", iteration)
				startTime := time.Now()

				if err := run(cmd, args); err != nil {
					log.Error("Command failed", "error", err, "iteration", iteration)
					return err
				}

				elapsed := time.Since(startTime)
				log.Info("<<< Iteration complete", 
					"number", iteration,
					"duration", elapsed,
					"next_run", time.Now().Add(duration),
				)

				time.Sleep(duration)
				iteration++
			}
		}
		return run(cmd, args)
	}

	cmd.Flags().StringVarP(&interval, "interval", "i", "", "Run commands on an interval (5m, 1h, 1d)")

	return cmd
}

func NewSyncCmd() *cobra.Command {
	var interval string

	cmd := &cobra.Command{
		Use:   "sync <integration>",
		Short: "Sync resources into Ctrlplane",
		Example: heredoc.Doc(`
			$ ctrlc sync tfe --interval 5m # Run every 5 minutes
			$ ctrlc sync tailscale --interval 1h # Run every hour
		`),
	}

	cmd.PersistentFlags().StringVar(&interval, "interval", "", "Run commands on an interval (5m, 1h, 1d)")

	cmd.AddCommand(AddIntervalSupport(terraform.NewSyncTerraformCmd()))
	cmd.AddCommand(AddIntervalSupport(tailscale.NewSyncTailscaleCmd()))

	return cmd
}

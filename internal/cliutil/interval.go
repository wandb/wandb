package cliutil

import (
	"time"

	"github.com/charmbracelet/log"
	"github.com/spf13/cobra"
)

func AddIntervalSupport(cmd *cobra.Command, defaultInterval string) *cobra.Command {
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

	cmd.Flags().StringVarP(&interval, "interval", "i", defaultInterval, "Run commands on an interval (5m, 1h, 1d)")

	return cmd
}

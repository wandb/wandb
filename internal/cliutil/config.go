package cliutil

import (
	"os"

	"github.com/spf13/cobra"
)

func GetString(cmd *cobra.Command, flag string) string {
	value, _ := cmd.Flags().GetString(flag)
	if value != "" {
		return value
	}

	value, _ = cmd.Flags().GetString(flag)
	if value != "" {
		return value
	}

	return os.Getenv(flag)
}

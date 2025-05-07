package github

import (
	"github.com/spf13/cobra"
)

// NewSyncGitHubCmd creates a new cobra command for syncing GitHub resources
func NewSyncGitHubCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "github",
		Short: "Sync GitHub resources into Ctrlplane",
	}

	// Add subcommands
	cmd.AddCommand(NewSyncPullRequestsCmd())

	return cmd
}

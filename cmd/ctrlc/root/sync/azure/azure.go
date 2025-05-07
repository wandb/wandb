package azure

import (
	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/azure/aks"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
)

// NewAzureCmd creates a new cobra command for syncing Azure resources
func NewAzureCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "azure",
		Short: "Sync Azure resources into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Azure credentials are configured via environment variables or Azure CLI
			
			# Sync all AKS clusters from the default subscription
			$ ctrlc sync azure aks
			
			# Sync all AKS clusters from a specific subscription
			$ ctrlc sync azure aks --subscription-id 00000000-0000-0000-0000-000000000000
			
			# Sync all AKS clusters every 5 minutes
			$ ctrlc sync azure aks --interval 5m
		`),
		// Add a RunE function that shows help to avoid nil pointer issues
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	// Add all Azure sync subcommands
	cmd.AddCommand(cliutil.AddIntervalSupport(aks.NewSyncAKSCmd(), ""))

	return cmd
}

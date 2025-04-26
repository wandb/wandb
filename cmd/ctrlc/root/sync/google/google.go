package google

import (
	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/google/bigtable"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/google/buckets"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/google/cloudsql"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/google/gke"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/google/networks"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/google/redis"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/google/secrets"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/google/vms"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
)

// NewGoogleCloudCmd creates a new cobra command for syncing Google Cloud resources
func NewGoogleCloudCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "google-cloud",
		Short: "Sync Google Cloud resources into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure Google Cloud credentials are configured via environment variables or application default credentials
			
			# Sync all VM instances from a project
			$ ctrlc sync google-cloud vms --project my-project
			
			# Sync all GKE clusters from a project
			$ ctrlc sync google-cloud gke --project my-project
			
			# Sync Cloud SQL instances from a project every 5 minutes
			$ ctrlc sync google-cloud cloudsql --project my-project --interval 5m
		`),
		// Add a RunE function that shows help to avoid nil pointer issues
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	// Add all Google Cloud sync subcommands
	cmd.AddCommand(cliutil.AddIntervalSupport(cloudsql.NewSyncCloudSQLCmd(), ""))
	cmd.AddCommand(cliutil.AddIntervalSupport(bigtable.NewSyncBigtableCmd(), ""))
	cmd.AddCommand(cliutil.AddIntervalSupport(buckets.NewSyncBucketsCmd(), ""))
	cmd.AddCommand(cliutil.AddIntervalSupport(redis.NewSyncRedisCmd(), ""))
	cmd.AddCommand(cliutil.AddIntervalSupport(gke.NewSyncGKECmd(), ""))
	cmd.AddCommand(cliutil.AddIntervalSupport(networks.NewSyncNetworksCmd(), ""))
	cmd.AddCommand(cliutil.AddIntervalSupport(vms.NewSyncVMsCmd(), ""))
	cmd.AddCommand(cliutil.AddIntervalSupport(secrets.NewSyncSecretsCmd(), ""))

	return cmd
}
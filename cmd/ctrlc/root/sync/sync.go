package sync

import (
	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/aws"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/azure"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/clickhouse"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/github"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/google"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/kubernetes"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/tailscale"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/terraform"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
)

func NewSyncCmd() *cobra.Command {
	var interval string

	cmd := &cobra.Command{
		Use:   "sync <integration>",
		Short: "Sync resources into Ctrlplane",
		Example: heredoc.Doc(`
			$ ctrlc sync tfe --interval 5m # Run every 5 minutes
			$ ctrlc sync tailscale --interval 1h # Run every hour
			$ ctrlc sync clickhouse # Run once
		`),
	}

	cmd.PersistentFlags().StringVar(&interval, "interval", "", "Run commands on an interval (5m, 1h, 1d)")

	cmd.AddCommand(cliutil.AddIntervalSupport(terraform.NewSyncTerraformCmd(), ""))
	cmd.AddCommand(cliutil.AddIntervalSupport(tailscale.NewSyncTailscaleCmd(), ""))
	cmd.AddCommand(cliutil.AddIntervalSupport(clickhouse.NewSyncClickhouseCmd(), ""))
	cmd.AddCommand(aws.NewAWSCmd())
	cmd.AddCommand(google.NewGoogleCloudCmd())
	cmd.AddCommand(azure.NewAzureCmd())
	cmd.AddCommand(kubernetes.NewSyncKubernetesCmd())
	cmd.AddCommand(github.NewSyncGitHubCmd())

	return cmd
}

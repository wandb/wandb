package sync

import (
	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/tailscale"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/terraform"
	"github.com/spf13/cobra"
)

func NewSyncCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "sync <integration>",
		Short: "Sync resources into Ctrlplane",
		Example: heredoc.Doc(`
			$ ctrlc sync aws-eks
			$ ctrlc sync google-gke
			$ ctrlc sync terraform
		`),
	}

	cmd.AddCommand(terraform.NewSyncTerraformCmd())
	cmd.AddCommand(tailscale.NewSyncTailscaleCmd())

	return cmd
}

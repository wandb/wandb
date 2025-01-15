package sync

import (
	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/tfe"
	"github.com/spf13/cobra"
)

func NewSyncCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "sync <integration>",
		Short: "Sync resources into Ctrlplane",
		Example: heredoc.Doc(`
			$ ctrlc sync aws-eks
			$ ctrlc sync google-gke
		`),
	}

	cmd.AddCommand(tfe.NewSyncTfeCmd())

	return cmd
}

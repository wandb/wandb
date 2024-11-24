package sync

import (
	"github.com/MakeNowJust/heredoc/v2"
	"github.com/spf13/cobra"
)

func NewRootCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "sync <integration>",
		Short: "Sync resources into Ctrlplane",
		Example: heredoc.Doc(`
			$ ctrlc sync aws-eks
			$ ctrlc sync google-gke
		`),
	}

	return cmd
}

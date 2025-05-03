package aws

import (
	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/aws/ec2"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/sync/aws/eks"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
)

// NewAWSCmd creates a new cobra command for syncing AWS resources
func NewAWSCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "aws",
		Short: "Sync AWS resources into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure AWS credentials are configured via environment variables or ~/.aws/credentials
			
			# Sync all EC2 instances from a region
			$ ctrlc sync aws ec2 --region us-west-2
			
			# Sync EC2 instances from a region every 5 minutes
			$ ctrlc sync aws ec2 --region us-west-2 --interval 5m
		`),
		// Add a RunE function that shows help to avoid nil pointer issues
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	// Add all AWS sync subcommands
	cmd.AddCommand(cliutil.AddIntervalSupport(ec2.NewSyncEC2Cmd(), ""))
	cmd.AddCommand(cliutil.AddIntervalSupport(eks.NewSyncEKSCmd(), ""))
	return cmd
}

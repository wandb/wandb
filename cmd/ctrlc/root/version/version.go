package version

import (
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
)

// Version is set at build time using ldflags
var (
	Version   = "dev"
	GitCommit = "unknown"
	BuildDate = "unknown"
)

// NewVersionCmd creates a new command that displays version information
func NewVersionCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "version",
		Short: "Display version information",
		Long:  `Display the version, git commit, and build date of the CLI.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return cliutil.HandleOutput(cmd, map[string]any{
				"version":   Version,
				"gitCommit": GitCommit,
				"buildDate": BuildDate,
			})
		},
	}

	cmd.Flags().String("template", "", "Template for output format. Accepts Go template format (e.g. --template='{{.status.phase}}')")
	cmd.Flags().String("format", "json", "Output format. Accepts 'json', 'yaml', or 'github-action'")

	return cmd
}
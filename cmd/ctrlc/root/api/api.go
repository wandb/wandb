package api

import (
	"fmt"
	"os"

	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/delete"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/get"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/update"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/upsert"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewAPICmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "api <action> <resource> [flags]",
		Short: "API commands",
		Long:  `Commands for interacting with the Ctrlplane API.`,
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			if apiURL == "" {
				fmt.Fprintln(cmd.ErrOrStderr(), "API URL is required. Set via --url flag or in config")
				os.Exit(1)
			}
			apiKey := viper.GetString("api-key")
			if apiKey == "" {
				fmt.Fprintln(cmd.ErrOrStderr(), "API key is required. Set via --api-key flag or in config")
				os.Exit(1)
			}

			templateFlag, _ := cmd.Flags().GetString("template")
			formatFlag, _ := cmd.Flags().GetString("format")

			if templateFlag != "" && formatFlag != "json" {
				fmt.Fprintln(cmd.ErrOrStderr(), "--template and --format flags cannot be used together")
				os.Exit(1)
			}
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}
	cmd.PersistentFlags().String("template", "", "Template for output format. Accepts Go template format (e.g. --template='{{.status.phase}}')")
	cmd.PersistentFlags().String("format", "json", "Output format. Accepts 'json', 'yaml', or 'github-action'")

	cmd.AddCommand(get.NewGetCmd())
	cmd.AddCommand(create.NewCreateCmd())
	cmd.AddCommand(upsert.NewUpsertCmd())
	cmd.AddCommand(delete.NewDeleteCmd())
	cmd.AddCommand(update.NewUpdateCmd())

	return cmd
}

package api

import (
	"fmt"

	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/create"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/get"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root/api/upsert"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewAPICmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "api <subcommand>",
		Short: "API commands",
		Long:  `Commands for interacting with the CtrlPlane API.`,
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			if apiURL == "" {
				return fmt.Errorf("API URL is required. Set via --url flag or in config")
			}
			apiKey := viper.GetString("api-key")
			if apiKey == "" {
				return fmt.Errorf("API key is required. Set via --api-key flag or in config")
			}
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}
	cmd.PersistentFlags().String("url", "", "API URL")
	cmd.PersistentFlags().String("api-key", "", "API key for authentication")
	cmd.PersistentFlags().String("template", "", "Template for output format. Accepts Go template format (e.g. --template='{{.status.phase}}')")
	cmd.PersistentFlags().String("format", "json", "Output format. Accepts 'json' or 'yaml'")

	viper.BindPFlag("url", cmd.PersistentFlags().Lookup("url"))
	viper.BindPFlag("api-key", cmd.PersistentFlags().Lookup("api-key"))

	cmd.AddCommand(get.NewGetCmd())
	cmd.AddCommand(create.NewCreateCmd())
	cmd.AddCommand(upsert.NewUpsertCmd())

	return cmd
}

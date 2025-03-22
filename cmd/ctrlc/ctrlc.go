package main

import (
	"os"

	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root"
	"github.com/mitchellh/go-homedir"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

var (
	cfgFile string
	cmd     = root.NewRootCmd()
)

func init() {
	cobra.OnInitialize(initConfig)
	cmd.PersistentFlags().StringVar(&cfgFile, "config", "", "Config file (default is $HOME/.ctrlc.yaml)")
	viper.BindEnv("config", "CTRLPLANE_CONFIG")

	cmd.PersistentFlags().String("url", "https://app.ctrlplane.dev", "API URL")
	viper.BindPFlag("url", cmd.PersistentFlags().Lookup("url"))
	viper.BindEnv("url", "CTRLPLANE_URL")

	cmd.PersistentFlags().String("api-key", "", "API key for authentication")
	viper.BindPFlag("api-key", cmd.PersistentFlags().Lookup("api-key"))
	viper.BindEnv("api-key", "CTRLPLANE_API_KEY")

	cmd.PersistentFlags().String("workspace", "", "Ctrlplane Workspace ID")
	viper.BindPFlag("workspace", cmd.PersistentFlags().Lookup("workspace"))
	viper.BindEnv("workspace", "CTRLPLANE_WORKSPACE")
}

func main() {
	if err := cmd.Execute(); err != nil {
		log.Error("Command failed", "error", err)
		os.Exit(1)
	}
}

func initConfig() {
	if cfgFile != "" {
		viper.SetConfigFile(cfgFile)
	} else {
		// Find home directory.
		home, err := homedir.Dir()
		if err != nil {
			log.Error("Can't find home directory", "error", err)
			os.Exit(1)
		}

		viper.AddConfigPath(home)
		viper.SetConfigName(".ctrlc")
		viper.SetConfigType("yaml")
		viper.SafeWriteConfig()
	}

	if err := viper.ReadInConfig(); err != nil {
		log.Error("Can't read config", "error", err)
		os.Exit(1)
	}
}

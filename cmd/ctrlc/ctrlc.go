package main

import (
	"fmt"
	"os"

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
}

func main() {
	cmd.Execute()
}

func initConfig() {
	if cfgFile != "" {
		viper.SetConfigFile(cfgFile)
	} else {
		// Find home directory.
		home, err := homedir.Dir()
		if err != nil {
			fmt.Println(err)
			os.Exit(1)
		}

		viper.AddConfigPath(home)
		viper.SetConfigName(".ctrlc")
		viper.SetConfigType("yaml")
		viper.SafeWriteConfig()
	}

	if err := viper.ReadInConfig(); err != nil {
		fmt.Println("Can't read config:", err)
		os.Exit(1)
	}
}

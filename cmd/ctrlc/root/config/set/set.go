package set

import (
	"fmt"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

// ValidConfigKeys defines the allowed configuration keys
var ValidConfigKeys = []string{
	"url",
	"api-key",
}

func NewSetCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "set <key> <value>",
		Short: "Set a configuration value",
		Long:  `Set a configuration value that will be persisted in the config file.`,
		Example: heredoc.Doc(`
			# Set API URL
			$ ctrlc config set url YOUR_INSTANCE_URL

			# Set API key
			$ ctrlc config set api-key YOUR_API_KEY
		`),
		Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			key := args[0]
			value := args[1]

			// Validate key is in allowed list
			valid := false
			for _, validKey := range ValidConfigKeys {
				if key == validKey {
					valid = true
					break
				}
			}
			if !valid {
				return fmt.Errorf("invalid config key: %s. Valid keys are: %v", key, ValidConfigKeys)
			}

			viper.Set(key, value)

			if err := viper.WriteConfig(); err != nil {
				return fmt.Errorf("failed to write config: %w", err)
			}

			fmt.Printf("Successfully set %s = %s\n", key, value)
			return nil
		},
	}

	return cmd
}

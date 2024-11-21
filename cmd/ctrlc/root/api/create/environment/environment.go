package environment

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewCreateEnvironmentCmd() *cobra.Command {
	var nameFlag string
	var releaseChannels []string
	var expiresIn string
	var system string
	var resourceFilter string
	cmd := &cobra.Command{
		Use:   "environment [flags]",
		Short: "Create a new environment",
		Long:  `Create a new environment with the specified name and configuration.`,
		Example: heredoc.Doc(`
			# Create a new environment
			$ ctrlc create environment --name my-environment --system 00000000-0000-0000-0000-000000000000

			# Create a new environment using Go template syntax
			$ ctrlc create environment --name my-environment --system 00000000-0000-0000-0000-000000000000 --template='{{.id}}'
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			body := api.CreateEnvironmentJSONRequestBody{}
			body.Name = nameFlag
			body.ReleaseChannels = &releaseChannels
			body.SystemId = system

			if resourceFilter != "" {
				var parsedFilter map[string]interface{}
				if err := json.Unmarshal([]byte(resourceFilter), &parsedFilter); err != nil {
					return fmt.Errorf("failed to parse target filter: %w", err)
				}
				body.ResourceFilter = &parsedFilter
			}

			if expiresIn != "" {
				duration, err := time.ParseDuration(expiresIn)
				if err != nil {
					return fmt.Errorf("failed to parse expires-in: %w", err)
				}
				expiresAt := time.Now().Add(duration)
				body.ExpiresAt = &expiresAt
			}

			resp, err := client.CreateEnvironment(cmd.Context(), body)
			if err != nil {
				return fmt.Errorf("failed to create environment: %w", err)
			}

			return cliutil.HandleOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVar(&nameFlag, "name", "", "Name of the environment (required)")
	cmd.Flags().StringVar(&system, "system", "", "ID of the system (required)")
	cmd.Flags().StringVar(&expiresIn, "expires-in", "", "Expiration time in duration (e.g. 1h)")
	cmd.Flags().StringSliceVar(&releaseChannels, "release-channel", []string{}, "Release channel in format <channelid>")
	cmd.Flags().StringVar(&resourceFilter, "resource-filter", "", "Resource filter as JSON string")

	cmd.MarkFlagRequired("name")
	cmd.MarkFlagRequired("system")

	return cmd
}

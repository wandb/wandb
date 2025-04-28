package release

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func safeConvertToReleaseStatus(stat string) (*api.UpdateReleaseJSONBodyStatus, error) {
	if stat == "" {
		return nil, nil
	}
	status := api.UpdateReleaseJSONBodyStatus(strings.ToLower(stat))
	return &status, nil
}

func NewUpdateReleaseCmd() *cobra.Command {
	var releaseID string
	var versionFlag string
	var metadata map[string]string
	var configArray map[string]string
	var jobAgentConfigArray map[string]string
	var links map[string]string
	var name string
	var status string
	var message string

	cmd := &cobra.Command{
		Use:   "release [flags]",
		Short: "Update a release",
		Long:  `Update a release with the specified version and configuration.`,
		Example: heredoc.Doc(`
			# Update a release
			$ ctrlc update release --release-id 1234567890 --version v1.0.0 --status ready
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			if releaseID == "" {
				return fmt.Errorf("release ID is required")
			}

			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			stat, err := safeConvertToReleaseStatus(status)
			if err != nil {
				return fmt.Errorf("failed to convert release status: %w", err)
			}

			if len(links) > 0 {
				linksJSON, err := json.Marshal(links)
				if err != nil {
					return fmt.Errorf("failed to marshal links: %w", err)
				}
				metadata["ctrlplane/links"] = string(linksJSON)
			}

			config := cliutil.ConvertConfigArrayToNestedMap(configArray)
			jobAgentConfig := cliutil.ConvertConfigArrayToNestedMap(jobAgentConfigArray)
			resp, err := client.UpdateRelease(cmd.Context(), releaseID, api.UpdateReleaseJSONRequestBody{
				Version:        cliutil.StringPtr(versionFlag),
				Metadata:       cliutil.StringMapPtr(metadata),
				Config:         cliutil.MapPtr(config),
				JobAgentConfig: cliutil.MapPtr(jobAgentConfig),
				Name:           cliutil.StringPtr(name),
				Status:         stat,
				Message:        cliutil.StringPtr(message),
			})
			if err != nil {
				return fmt.Errorf("failed to update release: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVarP(&releaseID, "release-id", "r", "", "ID of the release to update (required)")
	cmd.Flags().StringVarP(&versionFlag, "version", "v", "", "Version of the release")
	cmd.Flags().StringToStringVarP(&metadata, "metadata", "m", make(map[string]string), "Metadata key-value pairs (e.g. --metadata key=value)")
	cmd.Flags().StringToStringVarP(&configArray, "config", "c", make(map[string]string), "Config key-value pairs with nested values (can be specified multiple times)")
	cmd.Flags().StringToStringVarP(&jobAgentConfigArray, "job-agent-config", "j", make(map[string]string), "Job agent config key-value pairs (can be specified multiple times)")
	cmd.Flags().StringToStringVarP(&links, "link", "l", make(map[string]string), "Links key-value pairs (can be specified multiple times)")
	cmd.Flags().StringVarP(&name, "name", "n", "", "Name of the release")
	cmd.Flags().StringVarP(&status, "status", "s", "", "Status of the release")
	cmd.Flags().StringVar(&message, "message", "", "Message of the release")

	cmd.MarkFlagRequired("release-id")

	return cmd
}

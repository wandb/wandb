package deploymentversion

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

func safeConvertToDeploymentVersionStatus(stat string) (*api.UpdateDeploymentVersionJSONBodyStatus, error) {
	if stat == "" {
		return nil, nil
	}
	status := stat
	statusLower := strings.ToLower(status)
	if statusLower == "ready" || statusLower == "" {
		s := api.UpdateDeploymentVersionJSONBodyStatusReady
		return &s, nil
	}
	if statusLower == "building" {
		s := api.UpdateDeploymentVersionJSONBodyStatusBuilding
		return &s, nil
	}
	if statusLower == "failed" {
		s := api.UpdateDeploymentVersionJSONBodyStatusFailed
		return &s, nil
	}
	return nil, fmt.Errorf("invalid deployment version status: %s", status)
}

func NewUpdateDeploymentVersionCmd() *cobra.Command {
	var deploymentVersionID string
	var tag string
	var metadata map[string]string
	var configArray map[string]string
	var jobAgentConfigArray map[string]string
	var links map[string]string
	var name string
	var status string
	var message string

	cmd := &cobra.Command{
		Use:   "deployment-version [flags]",
		Short: "Update a deployment version",
		Long:  `Update a deployment version with the specified tag and configuration.`,
		Example: heredoc.Doc(`
			# Update a deployment version
			$ ctrlc update deployment-version --deployment-version-id 1234567890 --tag v1.0.0 --status ready
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			if deploymentVersionID == "" {
				return fmt.Errorf("deployment version ID is required")
			}

			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			stat, err := safeConvertToDeploymentVersionStatus(status)
			if err != nil {
				return fmt.Errorf("failed to convert deployment version status: %w", err)
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
			resp, err := client.UpdateDeploymentVersion(cmd.Context(), deploymentVersionID, api.UpdateDeploymentVersionJSONRequestBody{
				Tag:            cliutil.StringPtr(tag),
				Metadata:       cliutil.StringMapPtr(metadata),
				Config:         cliutil.MapPtr(config),
				JobAgentConfig: cliutil.MapPtr(jobAgentConfig),
				Name:           cliutil.StringPtr(name),
				Status:         stat,
				Message:        cliutil.StringPtr(message),
			})
			if err != nil {
				return fmt.Errorf("failed to update deployment version: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, resp)
		},
	}

	cmd.Flags().StringVarP(&deploymentVersionID, "deployment-version-id", "r", "", "ID of the deployment version to update (required)")
	cmd.Flags().StringVarP(&tag, "tag", "t", "", "Tag of the deployment version")
	cmd.Flags().StringToStringVarP(&metadata, "metadata", "m", make(map[string]string), "Metadata key-value pairs (e.g. --metadata key=value)")
	cmd.Flags().StringToStringVarP(&configArray, "config", "c", make(map[string]string), "Config key-value pairs with nested values (can be specified multiple times)")
	cmd.Flags().StringToStringVarP(&jobAgentConfigArray, "job-agent-config", "j", make(map[string]string), "Job agent config key-value pairs (can be specified multiple times)")
	cmd.Flags().StringToStringVarP(&links, "link", "l", make(map[string]string), "Links key-value pairs (can be specified multiple times)")
	cmd.Flags().StringVarP(&name, "name", "n", "", "Name of the deployment version")
	cmd.Flags().StringVarP(&status, "status", "s", "", "Status of the deployment version")
	cmd.Flags().StringVar(&message, "message", "", "Message of the deployment version")

	cmd.MarkFlagRequired("deployment-version-id")

	return cmd
}

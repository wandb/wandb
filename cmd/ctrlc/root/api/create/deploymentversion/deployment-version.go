package deploymentversion

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func safeConvertToDeploymentVersionStatus(status string) (*api.UpsertDeploymentVersionJSONBodyStatus, error) {
	statusLower := strings.ToLower(status)
	if statusLower == "ready" || statusLower == "" {
		s := api.UpsertDeploymentVersionJSONBodyStatusReady
		return &s, nil
	}
	if statusLower == "building" {
		s := api.UpsertDeploymentVersionJSONBodyStatusBuilding
		return &s, nil
	}
	if statusLower == "failed" {
		s := api.UpsertDeploymentVersionJSONBodyStatusFailed
		return &s, nil
	}
	return nil, fmt.Errorf("invalid deployment version status: %s", status)
}

func NewCreateDeploymentVersionCmd() *cobra.Command {
	var tag string
	var deploymentID []string
	var metadata map[string]string
	var configArray map[string]string
	var jobAgentConfigArray map[string]string
	var links map[string]string
	var createdAt string
	var name string
	var status string
	var message string

	cmd := &cobra.Command{
		Use:   "deployment-version [flags]",
		Short: "Create a deployment version",
		Long:  `Create a deployment version with the specified tag and configuration.`,
		Example: heredoc.Doc(`
			# Create a deployment version
			$ ctrlc create deployment-version --tag v1.0.0 --deployment 1234567890

			# Create a deployment version using Go template syntax
			$ ctrlc create deployment-version --tag v1.0.0 --deployment 1234567890 --template='{{.status.phase}}'

			# Create a deployment version for multiple deployments
			$ ctrlc create deployment-version --tag v1.0.0 --deployment 1234567890 --deployment 0987654321
		`),
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			var parsedTime *time.Time
			if createdAt != "" {
				t, err := time.Parse(time.RFC3339, createdAt)
				if err != nil {
					return fmt.Errorf("failed to parse created_at time: %w", err)
				}
				parsedTime = &t
			}

			if len(links) > 0 {
				linksJSON, err := json.Marshal(links)
				if err != nil {
					return fmt.Errorf("failed to marshal links: %w", err)
				}
				metadata["ctrlplane/links"] = string(linksJSON)
			}

			stat, err := safeConvertToDeploymentVersionStatus(status)
			if err != nil {
				return fmt.Errorf("failed to convert deployment version status: %w", err)
			}

			config := cliutil.ConvertConfigArrayToNestedMap(configArray)
			jobAgentConfig := cliutil.ConvertConfigArrayToNestedMap(jobAgentConfigArray)
			var response *http.Response
			for _, id := range deploymentID {
				resp, err := client.UpsertDeploymentVersion(cmd.Context(), api.UpsertDeploymentVersionJSONRequestBody{
					Tag:            tag,
					DeploymentId:   id,
					Metadata:       cliutil.StringMapPtr(metadata),
					CreatedAt:      parsedTime,
					Config:         cliutil.MapPtr(config),
					JobAgentConfig: cliutil.MapPtr(jobAgentConfig),
					Name:           cliutil.StringPtr(name),
					Status:         stat,
					Message:        cliutil.StringPtr(message),
				})
				if err != nil {
					return fmt.Errorf("failed to create deployment version: %w", err)
				}
				response = resp
			}

			return cliutil.HandleResponseOutput(cmd, response)
		},
	}

	// Add flags
	cmd.Flags().StringVarP(&tag, "tag", "t", "", "Tag of the deployment version (required)")
	cmd.Flags().StringArrayVarP(&deploymentID, "deployment", "d", []string{}, "IDs of the deployments (required, supports multiple)")
	cmd.Flags().StringToStringVarP(&metadata, "metadata", "m", make(map[string]string), "Metadata key-value pairs (e.g. --metadata key=value)")
	cmd.Flags().StringToStringVarP(&configArray, "config", "c", make(map[string]string), "Config key-value pairs with nested values (can be specified multiple times)")
	cmd.Flags().StringToStringVarP(&jobAgentConfigArray, "job-agent-config", "j", make(map[string]string), "Job agent config key-value pairs (can be specified multiple times)")
	cmd.Flags().StringToStringVarP(&links, "link", "l", make(map[string]string), "Links key-value pairs (can be specified multiple times)")
	cmd.Flags().StringVarP(&createdAt, "created-at", "r", "", "Created at timestamp (e.g. --created-at 2024-01-01T00:00:00Z) for the deployment version")
	cmd.Flags().StringVarP(&name, "name", "n", "", "Name of the deployment version")
	cmd.Flags().StringVarP(&status, "status", "s", string(api.UpsertDeploymentVersionJSONBodyStatusReady), "Status of the deployment version (one of: ready, building, failed)")
	cmd.Flags().StringVar(&message, "message", "", "Message of the deployment version")

	cmd.MarkFlagRequired("tag")
	cmd.MarkFlagRequired("deployment")

	return cmd
}

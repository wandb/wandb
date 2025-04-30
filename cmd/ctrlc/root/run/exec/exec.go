package exec

import (
	"fmt"

	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/pkg/jobagent"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewRunExecCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "exec",
		Short: "Execute commands directly when a job is received",
		RunE: func(cmd *cobra.Command, args []string) error {
			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			client, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}
			ja, err := jobagent.NewJobAgent(
				client,
				api.UpsertJobAgentJSONRequestBody{
					WorkspaceId: viper.GetString("workspace"),
					Name:        "exec",
					Type:        "exec",
				},
				&ExecRunner{},
			)
			if err != nil {
				return fmt.Errorf("failed to create job agent: %w", err)
			}
			if err := ja.RunQueuedJobs(); err != nil {
				log.Error("failed to run queued jobs", "error", err)
			}
			if err := ja.UpdateRunningJobs(); err != nil {
				log.Error("failed to check for jobs", "error", err)
			}
			return nil
		},
	}
}

package run

import (
	"log"
	"strings"
	"time"

	"github.com/ctrlplanedev/cli/pkg/agent"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

func NewAgentRunCmd() *cobra.Command {
	var agentName string
	var workspace string
	var metadata map[string]string
	var insecure bool
	var associatedResources []string

	cmd := &cobra.Command{
		Use:   "run",
		Short: "Run the agent",
		Long:  `Run the agent to establish connection with the proxy.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			proxyAddr := viper.GetString("url")
			proxyAddr = strings.TrimPrefix(proxyAddr, "https://")
			proxyAddr = strings.TrimPrefix(proxyAddr, "http://")

			if insecure {
				proxyAddr = "ws://" + proxyAddr
			} else {
				proxyAddr = "wss://" + proxyAddr
			}

			apiKey := viper.GetString("api-key")
			agent := agent.NewAgent(
				proxyAddr,
				agentName,
				agent.WithMetadata(metadata),
				agent.WithHeader("X-API-Key", apiKey),
				agent.WithHeader("X-Workspace", workspace),
				agent.WithAssociatedResources(associatedResources),
			)

			backoff := time.Second
			maxBackoff := time.Second * 30
			for {
				err := agent.Connect()
				if err == nil {
					<-agent.StopSignal
				}

				log.Printf("Failed to connect: %v. Retrying in %v...", err, backoff)
				time.Sleep(backoff)
				backoff *= 2
				if backoff > maxBackoff {
					backoff = maxBackoff
				}
			}
		},
		SilenceUsage: true,
	}

	cmd.Flags().StringVarP(&agentName, "name", "n", "", "Name for this agent")
	cmd.Flags().StringVarP(&workspace, "workspace", "w", "", "Workspace for this agent")
	cmd.Flags().StringToStringVar(&metadata, "metadata", make(map[string]string), "Metadata key-value pairs (e.g. --metadata key=value)")
	cmd.Flags().BoolVar(&insecure, "insecure", false, "Allow insecure connections (a.k use ws://)")
	cmd.Flags().StringArrayVarP(&associatedResources, "associated-resource", "r", []string{}, "Resource ID or Identifier to associate this agent with")

	cmd.MarkFlagRequired("workspace")
	cmd.MarkFlagRequired("name")

	return cmd
}

package run

import (
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/ctrlplanedev/cli/pkg/agent"
	"github.com/spf13/cobra"
)

func NewAgentRunCmd() *cobra.Command {
	var proxyAddr string
	var agentName string
	var workspace string
	var labels []string

	cmd := &cobra.Command{
		Use:   "run",
		Short: "Run the agent",
		Long:  `Run the agent to establish connection with the proxy.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			metadata := make(map[string]string)
			for _, label := range labels {
				key, value, found := strings.Cut(label, "=")
				if !found {
					return fmt.Errorf("invalid label format %q, expected key=value", label)
				}
				metadata[key] = value
			}

			proxyAddr := "ws://" + proxyAddr
			apiKey := os.Getenv("CTRLPLANE_API_KEY")
			agent := agent.NewAgent(
				proxyAddr,
				agentName,
				agent.WithMetadata(metadata),
				agent.WithHeader("X-API-Key", apiKey),
				agent.WithHeader("X-Workspace", workspace),
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

	cmd.Flags().StringVarP(&proxyAddr, "proxy", "p", "localhost:4000", "Proxy address to connect through")
	cmd.Flags().StringVarP(&agentName, "name", "n", "", "Name for this agent")
	cmd.Flags().StringVarP(&workspace, "workspace", "w", "", "Workspace for this agent")
	cmd.Flags().StringSliceVarP(&labels, "labels", "l", []string{}, "Labels in the format key=value")
	
	cmd.MarkFlagRequired("workspace")
	cmd.MarkFlagRequired("name")

	return cmd
}
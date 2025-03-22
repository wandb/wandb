package tailscale

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
	tsclient "github.com/tailscale/tailscale-client-go/v2"
)

type TailscaleConfig struct {
	ID            string   `json:"id"`
	Name          string   `json:"name"`
	Addresses     []string `json:"addresses"`
	OS            string   `json:"os"`
	Hostname      string   `json:"hostname"`
	ClientVersion string   `json:"clientVersion"`
	IsExternal    bool     `json:"isExternal"`
	MachineKey    string   `json:"machineKey"`
	NodeKey       string   `json:"nodeKey"`
}

func (t *TailscaleConfig) Struct() map[string]interface{} {
	b, _ := json.Marshal(t)
	var m map[string]interface{}
	json.Unmarshal(b, &m)
	return m
}

func NewSyncTailscaleCmd() *cobra.Command {
	var providerName string
	var tailscaleApiUrl string
	var tailnet string
	var tailscaleApiKey string
	var tailscaleOauthClientId string
	var tailscaleOauthClientSecret string

	cmd := &cobra.Command{
		Use:   "tailscale",
		Short: "Sync Tailscale VMs into Ctrlplane",
		Example: heredoc.Doc(`
			$ ctrlc sync tailscale --workspace 2a7c5560-75c9-4dbe-be74-04ee33bf8188
		`),
		PreRunE: func(cmd *cobra.Command, args []string) error {
			if tailscaleApiKey == "" && (tailscaleOauthClientId == "" || tailscaleOauthClientSecret == "") {
				return fmt.Errorf("either tailscale-key or tailscale-oauth-id and tailscale-oauth-secret must be provided")
			}
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			log.Info("Syncing Tailscale VMs into Ctrlplane")

			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			workspaceId := viper.GetString("workspace")
			ctrlplaneClient, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			baseURL, err := url.Parse(tailscaleApiUrl)
			if err != nil {
				return fmt.Errorf("failed to parse tailscale API URL: %w", err)
			}

			tsc := &tsclient.Client{
				BaseURL: baseURL,
				Tailnet: tailnet,
				APIKey:  tailscaleApiKey,
			}

			if tailscaleApiKey == "" {
				tsc.HTTP = tsclient.OAuthConfig{
					ClientID:     tailscaleOauthClientId,
					ClientSecret: tailscaleOauthClientSecret,
					Scopes:       []string{"devices:core:read"},
				}.HTTPClient()
			}

			ctx := context.Background()
			devices, err := tsc.Devices().List(ctx)
			if err != nil {
				return fmt.Errorf("failed to list devices: %w", err)
			}

			resources := []api.AgentResource{}
			for _, device := range devices {
				metadata := map[string]string{}
				metadata["tailscale/id"] = device.ID
				metadata["tailscale/name"] = device.Name
				metadata["tailscale/os"] = device.OS
				metadata["tailscale/hostname"] = device.Hostname
				metadata["tailscale/addresses"] = strings.Join(device.Addresses, ",")
				metadata["tailscale/client-version"] = device.ClientVersion
				metadata["tailscale/is-external"] = strconv.FormatBool(device.IsExternal)
				metadata["tailscale/update-available"] = strconv.FormatBool(device.UpdateAvailable)
				metadata["tailscale/user"] = device.User
				metadata["tailscale/blocks-incoming-connections"] = strconv.FormatBool(device.BlocksIncomingConnections)

				metadata["tailscale/status"] = "offline"
				if time.Since(device.LastSeen.Time) < time.Minute {
					metadata["tailscale/status"] = "connected"
				}

				for _, tag := range device.Tags {
					v := strings.TrimPrefix(tag, "tag:")
					metadata[fmt.Sprintf("tailscale/tag/%s", v)] = "true"
				}

				config := TailscaleConfig{
					ID:            device.ID,
					Name:          device.Name,
					Addresses:     device.Addresses,
					OS:            device.OS,
					Hostname:      device.Hostname,
					MachineKey:    device.MachineKey,
					ClientVersion: device.ClientVersion,
					IsExternal:    device.IsExternal,
					NodeKey:       device.NodeKey,
				}

				name := strings.Split(device.Name, ".")[0]
				resources = append(resources, api.AgentResource{
					Version:    "tailscale/v1",
					Kind:       "Device",
					Name:       name,
					Identifier: fmt.Sprintf("%s/%s", tailnet, device.ID),
					Config:     config.Struct(),
					Metadata:   metadata,
				})
			}

			log.Info("Upserting resources", "count", len(resources))

			providerName := fmt.Sprintf("tailscale-%s", tailnet)
			rp, err := api.NewResourceProvider(ctrlplaneClient, workspaceId, providerName)
			if err != nil {
				return fmt.Errorf("failed to create resource provider: %w", err)
			}

			upsertResp, err := rp.UpsertResource(ctx, resources)
			log.Info("Response from upserting resources", "status", upsertResp.Status)
			if err != nil {
				return fmt.Errorf("failed to upsert resources: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, upsertResp)
		},
	}

	cmd.Flags().StringVarP(&providerName, "provider", "p", "tailscale", "The name of the provider to use")
	cmd.Flags().StringVarP(&tailnet, "tailnet", "t", "", "The tailnet to sync")
	cmd.Flags().StringVarP(&tailscaleApiUrl, "tailscale-url", "u", "https://api.tailscale.com", "The URL of the Tailscale API")
	cmd.Flags().StringVarP(&tailscaleApiKey, "tailscale-key", "k", os.Getenv("TAILSCALE_API_KEY"), "The API key to use")

	cmd.MarkFlagRequired("tailnet")

	cmd.Flags().StringVarP(&tailscaleOauthClientId, "tailscale-oauth-id", "c", os.Getenv("TAILSCALE_OAUTH_CLIENT_ID"), "The OAuth client ID to use")
	cmd.Flags().StringVarP(&tailscaleOauthClientSecret, "tailscale-oauth-secret", "s", os.Getenv("TAILSCALE_OAUTH_CLIENT_SECRET"), "The OAuth client secret to use")

	return cmd
}

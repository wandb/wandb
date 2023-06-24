package server

import (
	"strings"

	"github.com/wandb/wandb/nexus/pkg/service"

	"github.com/wandb/wandb/nexus/pkg/auth"
)

type Settings struct {
	BaseURL     string
	ApiKey      string
	Offline     bool
	SyncFile    string
	NoWrite     bool
	LogInternal string
}

func NewSettings(s map[string]*service.SettingsValue) *Settings {
	settings := Settings{
		BaseURL:     s["base_url"].GetStringValue(),
		ApiKey:      s["api_key"].GetStringValue(),
		Offline:     s["offline"].GetBoolValue(),
		SyncFile:    s["sync_file"].GetStringValue(),
		LogInternal: s["log_internal"].GetStringValue(),
	}

	settings.parseNetrc()
	return &settings
}

func (s *Settings) parseNetrc() {
	if s.ApiKey != "" {
		return
	}
	host := strings.TrimPrefix(s.BaseURL, "https://")
	host = strings.TrimPrefix(host, "http://")

	netlist, err := auth.ReadNetrc()
	if err != nil {
		LogFatalError("cant read netrc", err)
	}

	for i := 0; i < len(netlist); i++ {
		if netlist[i].Machine == host {
			s.ApiKey = netlist[i].Password
			break
		}
	}
}

package server

import (
	"strings"

	"github.com/wandb/wandb/nexus/pkg/auth"
	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
)

type Settings struct {
	BaseURL     string
	ApiKey      string
	Offline     bool
	SyncFile    string
	NoWrite     bool
	LogInternal string
	FilesDir    string
	XPython     string
	XOs         string
	XCuda       string
	// XArgs       []string
	Host    string
	Program string
}

func NewSettings(s *service.Settings) *Settings {
	settings := Settings{
		BaseURL:     s.GetBaseUrl().GetValue(),
		ApiKey:      s.GetApiKey().GetValue(),
		Offline:     s.GetXOffline().GetValue(),
		SyncFile:    s.GetSyncFile().GetValue(),
		LogInternal: s.GetLogInternal().GetValue(),
		FilesDir:    s.GetFilesDir().GetValue(),
		XPython:     s.GetXPython().GetValue(),
		XOs:         s.GetXOs().GetValue(),
		XCuda:       s.GetXCuda().GetValue(),
		// XArgs:       s["_args"].GetTupleValue(),
		Host:    s.GetHost().GetValue(),
		Program: s.GetProgram().GetValue(),
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
		LogFatalError(slog.Default(), "cant read netrc", err)
	}

	for i := 0; i < len(netlist); i++ {
		if netlist[i].Machine == host {
			s.ApiKey = netlist[i].Password
			break
		}
	}
}

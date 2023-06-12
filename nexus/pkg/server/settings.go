package server

import (
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/wandb/wandb/nexus/pkg/auth"
)

type Settings struct {
	BaseURL  string
	ApiKey   string
	Offline  bool
	SyncFile string
	NoWrite  bool
}

func (s *Settings) parseNetrc() {
	if s.ApiKey != "" {
		return
	}
	host := strings.TrimPrefix(s.BaseURL, "https://")
	host = strings.TrimPrefix(host, "http://")

	netlist, err := auth.ReadNetrc()
	if err != nil {
		log.Fatal(err)
	}

	for i := 0; i < len(netlist); i++ {
		if netlist[i].Machine == host {
			s.ApiKey = netlist[i].Password
			break
		}
	}
}

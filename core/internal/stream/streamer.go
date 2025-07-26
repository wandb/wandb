package stream

import (
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type Streamer interface {
	AddResponders(entries ...ResponderEntry)
	GetSettings() *settings.Settings
	UpdateSettings(newSettings *settings.Settings)
	Start()
	HandleRecord(record *spb.Record)
	Close()
	FinishAndClose(exitCode int32)
}

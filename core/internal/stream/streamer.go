package stream

import (
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Streamer is an interface for ingesting records from a client.
type Streamer interface {
	Start()
	Close()
	HandleRecord(record *spb.Record)
	GetSettings() *settings.Settings
	AddResponders(entries ...ResponderEntry)
	FinishAndClose(exitCode int32)
}

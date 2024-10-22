package stream

import (
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type Responder interface {
	Respond(response *spb.ServerResponse)
	GetID() string
}

type Stream interface {
	AddResponders(responders ...Responder)
	UpdateSettings(settings *settings.Settings)
	GetSettings() *settings.Settings
	UpdateRunURLTag() // TODO: remove this
	Start()
	HandleRecord(rec *spb.Record)
	Close()
	FinishAndClose(exitCode int32)
}

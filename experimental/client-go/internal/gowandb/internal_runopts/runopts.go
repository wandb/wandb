package internal_runopts

import (
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/experimental/client-go/gowandb/opts/runopts"
)

func WithTelemetry(telemetry *service.TelemetryRecord) runopts.RunOption {
	return func(p *runopts.RunParams) {
		p.Telemetry = telemetry
	}
}

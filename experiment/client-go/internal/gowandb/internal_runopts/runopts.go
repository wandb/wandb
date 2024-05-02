package internal_runopts

import (
	"github.com/wandb/wandb/core/pkg/gowandb/opts/runopts"
	"github.com/wandb/wandb/core/pkg/service"
)

func WithTelemetry(telemetry *service.TelemetryRecord) runopts.RunOption {
	return func(p *runopts.RunParams) {
		p.Telemetry = telemetry
	}
}

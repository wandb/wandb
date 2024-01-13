package internal_runopts

import (
	"github.com/wandb/wandb/core/internal/gowandb/client/opts/runopts"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

func WithTelemetry(telemetry *pb.TelemetryRecord) runopts.RunOption {
	return func(p *runopts.RunParams) {
		p.Telemetry = telemetry
	}
}

package filestream

import (
	"time"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/systemmetrics"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// SystemMetricsUpdate contains a typed system metrics sample.
type SystemMetricsUpdate struct {
	StartTime time.Time
	Record    *spb.SystemMetricsRecord
}

func (u *SystemMetricsUpdate) Apply(ctx UpdateContext) error {
	if ctx.UseProto {
		ctx.MakeRequest(&FileStreamRequest{
			SystemMetrics:          []*spb.SystemMetricsRecord{u.Record},
			SystemMetricsSizeBytes: proto.Size(u.Record),
			SystemMetricsStartTime: u.StartTime,
		})
		return nil
	}

	if stats := systemmetrics.LegacyStats(u.Record); stats != nil {
		return (&StatsUpdate{StartTime: u.StartTime, Record: stats}).Apply(ctx)
	}
	return nil
}

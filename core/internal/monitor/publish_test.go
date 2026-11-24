package monitor

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestPublish_TypedOnlyWithTheSetting(t *testing.T) {
	for _, typed := range []bool{true, false} {
		work := runworktest.New()
		sm := (&SystemMonitorFactory{
			Logger: observabilitytest.NewTestLogger(t),
			Settings: settings.From(&spb.Settings{
				XDisableStats: wrapperspb.Bool(true),
				XStatsTyped:   wrapperspb.Bool(typed),
			}),
			SymonResourceManager: NewSymonResourceManager(false),
			WriterID:             "writer-1",
		}).New(work)

		sm.publish(context.Background(), &spb.SubscribeResponse{
			Sample: &spb.SystemMetricsRecord{Host: &spb.HostMetrics{
				Network: &spb.NetworkMetrics{SentBytes: proto.Uint64(7)},
			}},
		})

		records := work.AllRecords()
		require.Len(t, records, 1)
		if typed {
			assert.Equal(t, "writer-1", records[0].GetSystemMetrics().GetWriter().GetId())
			assert.EqualValues(t, 1, records[0].GetSystemMetrics().GetSequence())

			// Two dropped samples leave a gap of two in the sequence.
			sm.publish(context.Background(), &spb.SubscribeResponse{
				Sample: &spb.SystemMetricsRecord{
					DroppedSamples: 2,
					Host:           &spb.HostMetrics{UptimeS: proto.Float64(1)},
				},
			})
			records = work.AllRecords()
			require.Len(t, records, 2)
			assert.EqualValues(t, 4, records[1].GetSystemMetrics().GetSequence())
		} else {
			item := records[0].GetStats().GetItem()[0]
			assert.Equal(t, "network.sent", item.GetKey())
			assert.Equal(t, "7", item.GetValueJson())
		}
	}
}

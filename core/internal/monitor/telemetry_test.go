package monitor

import (
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestTelemetry(t *testing.T) {
	sm := &SystemMonitor{settings: settings.From(&spb.Settings{})}

	// An empty Env or Feature would be encoded as null in the run config.
	assert.Nil(t, sm.telemetry(&spb.EnvironmentRecord{Host: "cpu-only"}))

	telemetry := sm.telemetry(&spb.EnvironmentRecord{
		GpuNvidia: []*spb.GpuNvidiaInfo{{Name: "H100"}},
	})
	assert.True(t, telemetry.GetEnv().GetNvidiaGpu())
	assert.Nil(t, telemetry.GetFeature())
}

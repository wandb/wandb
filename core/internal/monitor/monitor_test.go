package monitor_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func newTestSystemMonitor() *monitor.SystemMonitor {
	return monitor.NewSystemMonitor(
		monitor.SystemMonitorParams{
			Logger:             observability.NewNoOpLogger(),
			Settings:           settings.From(&spb.Settings{}),
			ExtraWork:          runworktest.New(),
			GpuResourceManager: monitor.NewGPUResourceManager(false),
		},
	)
}

func TestSystemMonitor_BasicStateTransitions(t *testing.T) {
	sm := newTestSystemMonitor()

	assert.Equal(t, monitor.StateStopped, sm.GetState())

	sm.Start(nil)
	assert.Equal(t, monitor.StateRunning, sm.GetState())

	sm.Pause()
	assert.Equal(t, monitor.StatePaused, sm.GetState())

	sm.Resume()
	assert.Equal(t, monitor.StateRunning, sm.GetState())

	sm.Finish()
	assert.Equal(t, monitor.StateStopped, sm.GetState())
}

func TestSystemMonitor_RepeatedCalls(t *testing.T) {
	sm := newTestSystemMonitor()

	// Multiple starts
	sm.Start(nil)
	sm.Start(nil)
	assert.Equal(t, monitor.StateRunning, sm.GetState())

	// Multiple pauses
	sm.Pause()
	sm.Pause()
	assert.Equal(t, monitor.StatePaused, sm.GetState())

	// Multiple resumes
	sm.Resume()
	sm.Resume()
	assert.Equal(t, monitor.StateRunning, sm.GetState())

	// Multiple finishes
	sm.Finish()
	sm.Finish()
	assert.Equal(t, monitor.StateStopped, sm.GetState())
}

func TestSystemMonitor_UnexpectedTransitions(t *testing.T) {
	sm := newTestSystemMonitor()

	// Resume when stopped
	sm.Resume()
	assert.Equal(t, monitor.StateStopped, sm.GetState(), "Resume should not change state when stopped")

	// Pause when stopped
	sm.Pause()
	assert.Equal(t, monitor.StateStopped, sm.GetState(), "Pause should not change state when stopped")

	// Start and then unexpected transitions
	sm.Start(nil)
	assert.Equal(t, monitor.StateRunning, sm.GetState(), "Start should change state to running")

	sm.Start(nil) // Start when already running
	assert.Equal(t, monitor.StateRunning, sm.GetState(), "Start should not change state when already running")

	sm.Resume() // Resume when running
	assert.Equal(t, monitor.StateRunning, sm.GetState(), "Resume should not change state when running")

	// Pause and then unexpected transitions
	sm.Pause()
	assert.Equal(t, monitor.StatePaused, sm.GetState(), "Pause should change state to paused")

	sm.Pause() // Pause when already paused
	assert.Equal(t, monitor.StatePaused, sm.GetState(), "Pause should not change state when already paused")

	sm.Start(nil) // Start when paused
	assert.Equal(t, monitor.StatePaused, sm.GetState(), "Start should not change state when paused")

	// Finish from any state
	sm.Finish()
	assert.Equal(t, monitor.StateStopped, sm.GetState(), "Finish should change state to stopped from paused")

	sm.Start(nil)
	sm.Finish()
	assert.Equal(t, monitor.StateStopped, sm.GetState(), "Finish should change state to stopped from running")
}

func TestSystemMonitor_FullCycle(t *testing.T) {
	sm := newTestSystemMonitor()

	// Full cycle of operations
	sm.Start(nil)
	assert.Equal(t, monitor.StateRunning, sm.GetState())

	sm.Pause()
	assert.Equal(t, monitor.StatePaused, sm.GetState())

	sm.Resume()
	assert.Equal(t, monitor.StateRunning, sm.GetState())

	sm.Pause()
	assert.Equal(t, monitor.StatePaused, sm.GetState())

	sm.Resume()
	assert.Equal(t, monitor.StateRunning, sm.GetState())

	sm.Finish()
	assert.Equal(t, monitor.StateStopped, sm.GetState())

	// Start again after finishing
	sm.Start(nil)
	assert.Equal(t, monitor.StateRunning, sm.GetState())

	sm.Finish()
	assert.Equal(t, monitor.StateStopped, sm.GetState())
}

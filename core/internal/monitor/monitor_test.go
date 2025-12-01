package monitor_test

import (
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func newTestSystemMonitor(t *testing.T) *monitor.SystemMonitor {
	t.Helper()
	factory := &monitor.SystemMonitorFactory{
		Logger:             observabilitytest.NewTestLogger(t),
		Settings:           settings.From(&spb.Settings{}),
		GpuResourceManager: monitor.NewGPUResourceManager(false),
	}
	return factory.New(runworktest.New())
}

func TestSystemMonitor_BasicStateTransitions(t *testing.T) {
	sm := newTestSystemMonitor(t)

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
	sm := newTestSystemMonitor(t)

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
	sm := newTestSystemMonitor(t)

	// Resume when stopped
	sm.Resume()
	assert.Equal(
		t,
		monitor.StateStopped,
		sm.GetState(),
		"Resume should not change state when stopped",
	)

	// Pause when stopped
	sm.Pause()
	assert.Equal(
		t,
		monitor.StateStopped,
		sm.GetState(),
		"Pause should not change state when stopped",
	)

	// Start and then unexpected transitions
	sm.Start(nil)
	assert.Equal(t, monitor.StateRunning, sm.GetState(), "Start should change state to running")

	sm.Start(nil) // Start when already running
	assert.Equal(
		t,
		monitor.StateRunning,
		sm.GetState(),
		"Start should not change state when already running",
	)

	sm.Resume() // Resume when running
	assert.Equal(
		t,
		monitor.StateRunning,
		sm.GetState(),
		"Resume should not change state when running",
	)

	// Pause and then unexpected transitions
	sm.Pause()
	assert.Equal(t, monitor.StatePaused, sm.GetState(), "Pause should change state to paused")

	sm.Pause() // Pause when already paused
	assert.Equal(
		t,
		monitor.StatePaused,
		sm.GetState(),
		"Pause should not change state when already paused",
	)

	sm.Start(nil) // Start when paused
	assert.Equal(t, monitor.StatePaused, sm.GetState(), "Start should not change state when paused")

	// Finish from any state
	sm.Finish()
	assert.Equal(
		t,
		monitor.StateStopped,
		sm.GetState(),
		"Finish should change state to stopped from paused",
	)

	sm.Start(nil)
	sm.Finish()
	assert.Equal(
		t,
		monitor.StateStopped,
		sm.GetState(),
		"Finish should change state to stopped from running",
	)
}

func TestSystemMonitor_FullCycle(t *testing.T) {
	sm := newTestSystemMonitor(t)

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

func TestShouldCaptureSamplingErr(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want bool
	}{
		{
			"NetstatMissing",
			errors.New(`exec: "netstat": executable file not found in $PATH`),
			false,
		},
		{"GrpcUnavailable", status.Error(codes.Unavailable, "connection error"), false},
		{
			"ConnRefused",
			errors.New(
				`transport: Error while dialing: dial unix /tmp/x.sock: connect: connection refused`,
			),
			false,
		},
		{"WinIncorrectFunction", errors.New("Incorrect function."), false},
		{
			"MissingProcDiskstats",
			errors.New("open /proc/diskstats: no such file or directory"),
			false,
		},
		{"OtherError", errors.New("some other error"), true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := monitor.ShouldCaptureSamplingError(tt.err); got != tt.want {
				t.Fatalf("ShouldCaptureSamplingError() = %v, want %v", got, tt.want)
			}
		})
	}
}

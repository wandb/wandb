package monitor_test

import (
	"errors"
	"testing"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/shirou/gopsutil/v4/process"
	"github.com/stretchr/testify/assert"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func newTestSystemMonitor(t *testing.T) *monitor.SystemMonitor {
	t.Helper()
	factory := &monitor.SystemMonitorFactory{
		Logger:             observabilitytest.NewTestLogger(t),
		Settings:           settings.From(&spb.Settings{XDisableStats: wrapperspb.Bool(true)}),
		XPUResourceManager: monitor.NewXPUResourceManager(false),
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
		{"ProcessExited", process.ErrorProcessNotRunning, false},
		{
			"ProcessExitedWithOtherError",
			errors.Join(process.ErrorProcessNotRunning, errors.New("disk read failed")),
			true,
		},
		{
			"ProcessExitedWithOtherExpectedError",
			errors.Join(
				process.ErrorProcessNotRunning,
				status.Error(codes.Unavailable, "disconnected"),
			),
			false,
		},
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

// waitForSample waits until the monitor has taken a sample.
//
// It polls the monitor's buffer rather than FakeRunWork.AllRecords, which
// races with work still being added.
func waitForSample(t *testing.T, sm *monitor.SystemMonitor) {
	t.Helper()
	assert.Eventually(t,
		func() bool { return len(sm.GetBuffer()) > 0 },
		5*time.Second, 10*time.Millisecond)
}

func hasStatsRecord(work *runworktest.FakeRunWork) bool {
	for _, record := range work.AllRecords() {
		if record.GetStats() != nil {
			return true
		}
	}
	return false
}

func serverInfoClient(versionInfoJSON string) *gqlmock.MockClient {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(
		gqlmock.WithOpName("ServerInfo"),
		`{"serverInfo":{"latestLocalVersionInfo":`+versionInfoJSON+`}}`,
	)
	return client
}

func TestSystemMonitor_SendsStatsImmediately_OnSupportedServers(t *testing.T) {
	errorClient := gqlmock.NewMockClient()
	errorClient.StubMatchWithError(
		gqlmock.WithOpName("ServerInfo"),
		errors.New("test error"),
	)

	for name, client := range map[string]graphql.Client{
		"0.78.0":             serverInfoClient(`{"versionOnThisInstanceString":"0.78.0"}`),
		"0.86.0":             serverInfoClient(`{"versionOnThisInstanceString":"0.86.0"}`),
		"development":        serverInfoClient(`{"versionOnThisInstanceString":"development"}`),
		"cloud (no version)": serverInfoClient(`null`),
		"lookup error":       errorClient,
		"no client":          nil,
	} {
		t.Run(name, func(t *testing.T) {
			sm, work := newSamplingTestSystemMonitor(t, client)

			sm.Start(nil)
			waitForSample(t, sm)
			sm.Finish()

			assert.True(t, hasStatsRecord(work))
			assert.Empty(t, sm.ClearHeld())
		})
	}
}

func TestSystemMonitor_HoldsStats_OnServersBefore0_78(t *testing.T) {
	for _, version := range []string{"0.77.1", "0.68.2"} {
		t.Run(version, func(t *testing.T) {
			sm, work := newSamplingTestSystemMonitor(t,
				serverInfoClient(`{"versionOnThisInstanceString":"`+version+`"}`))

			sm.Start(nil)
			waitForSample(t, sm)
			sm.Finish()

			assert.False(t, hasStatsRecord(work))
			held := sm.ClearHeld()
			assert.NotEmpty(t, held)
			for _, record := range held {
				assert.NotNil(t, record.GetStats())
			}
			assert.Empty(t, sm.ClearHeld(), "ClearHeld should clear")
		})
	}
}

func TestSystemMonitor_FinishDoesNotWaitForVersionCheck(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchHang(gqlmock.WithOpName("ServerInfo"))
	sm, _ := newSamplingTestSystemMonitor(t, client)

	sm.Start(nil)
	finished := make(chan struct{})
	go func() {
		sm.Finish()
		close(finished)
	}()

	select {
	case <-finished:
	case <-time.After(5 * time.Second):
		t.Fatal("Finish blocked on the server version check")
	}
}

func TestSystemMonitor_ClearHeld_NilMonitor(t *testing.T) {
	var sm *monitor.SystemMonitor
	assert.Nil(t, sm.ClearHeld())
}

// newSamplingTestSystemMonitor returns a monitor with stats enabled and a
// sampling interval long enough that only the sample at startup happens
// during a test.
//
// It keeps samples in memory so tests can wait for one with GetBuffer.
func newSamplingTestSystemMonitor(
	t *testing.T,
	graphqlClient graphql.Client,
) (*monitor.SystemMonitor, *runworktest.FakeRunWork) {
	t.Helper()
	work := runworktest.New()
	factory := &monitor.SystemMonitorFactory{
		Logger: observabilitytest.NewTestLogger(t),
		Settings: settings.From(&spb.Settings{
			XStatsSamplingInterval: wrapperspb.Double(3600),
			XStatsBufferSize:       wrapperspb.Int32(-1),
		}),
		XPUResourceManager: monitor.NewXPUResourceManager(false),
		GraphqlClient:      graphqlClient,
	}
	return factory.New(work), work
}

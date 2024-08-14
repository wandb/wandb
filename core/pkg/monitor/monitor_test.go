package monitor_test

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
	"github.com/wandb/wandb/core/pkg/monitor" // Import the monitor package
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

// MockAsset is a mock implementation of the Asset interface
type MockAsset struct {
	mock.Mock
}

func (m *MockAsset) Name() string {
	args := m.Called()
	return args.String(0)
}

func (m *MockAsset) SampleMetrics() error {
	args := m.Called()
	return args.Error(0)
}

func (m *MockAsset) AggregateMetrics() map[string]float64 {
	args := m.Called()
	return args.Get(0).(map[string]float64)
}

func (m *MockAsset) ClearMetrics() {
	m.Called()
}

func (m *MockAsset) IsAvailable() bool {
	args := m.Called()
	return args.Bool(0)
}

func (m *MockAsset) Probe() *service.MetadataRequest {
	args := m.Called()
	return args.Get(0).(*service.MetadataRequest)
}

// MockExtraWork is a mock implementation of the ExtraWork interface
type MockExtraWork struct {
	mock.Mock
}

func (m *MockExtraWork) AddRecordOrCancel(done <-chan struct{}, record *service.Record) {
	m.Called(done, record)
}

func (m *MockExtraWork) AddRecord(record *service.Record) {
	m.Called(record)
}

func (m *MockExtraWork) BeforeEndCtx() context.Context {
	args := m.Called()
	return args.Get(0).(context.Context)
}

// TODO: this test is very useful, but time sensitive and can in
// principle fail if the system is under heavy load. We should
// consider refactoring it to make it more reliable.
func TestSystemMonitor_Start(t *testing.T) {
	mockAsset := new(MockAsset)
	mockAsset.On("IsAvailable").Return(true)
	mockAsset.On("SampleMetrics").Return(nil)
	mockAsset.On("AggregateMetrics").Return(map[string]float64{"test": 1.0})
	mockAsset.On("ClearMetrics").Return()
	mockAsset.On("Probe").Return(&service.MetadataRequest{})

	mockExtraWork := new(MockExtraWork)
	mockExtraWork.On("AddRecordOrCancel", mock.Anything, mock.Anything).Return()

	settings := &service.Settings{
		XStatsSampleRateSeconds: &wrapperspb.DoubleValue{Value: 0.01},
		XStatsSamplesToAverage:  &wrapperspb.Int32Value{Value: 1},
	}
	sm := monitor.New(
		observability.NewNoOpLogger(),
		settings,
		mockExtraWork,
	)

	sm.SetAssets([]monitor.Asset{mockAsset})

	sm.Start()
	assert.Equal(t, monitor.StateRunning, sm.GetState())

	time.Sleep(200 * time.Millisecond)

	sm.Finish()
	assert.Equal(t, monitor.StateStopped, sm.GetState())

	mockAsset.AssertExpectations(t)
	mockExtraWork.AssertExpectations(t)
}

type DummyExtraWork struct{}

func (d *DummyExtraWork) AddRecordOrCancel(done <-chan struct{}, record *service.Record) {
	// Do nothing
}

func (d *DummyExtraWork) AddRecord(record *service.Record) {
	// Do nothing
}

func (d *DummyExtraWork) BeforeEndCtx() context.Context {
	return context.Background()
}

func newTestSystemMonitor() *monitor.SystemMonitor {
	settings := &service.Settings{}
	return monitor.New(
		observability.NewNoOpLogger(),
		settings,
		&DummyExtraWork{},
	)
}

func TestSystemMonitor_BasicStateTransitions(t *testing.T) {
	sm := newTestSystemMonitor()

	assert.Equal(t, monitor.StateStopped, sm.GetState())

	sm.Start()
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
	sm.Start()
	sm.Start()
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
	sm.Start()
	assert.Equal(t, monitor.StateRunning, sm.GetState(), "Start should change state to running")

	sm.Start() // Start when already running
	assert.Equal(t, monitor.StateRunning, sm.GetState(), "Start should not change state when already running")

	sm.Resume() // Resume when running
	assert.Equal(t, monitor.StateRunning, sm.GetState(), "Resume should not change state when running")

	// Pause and then unexpected transitions
	sm.Pause()
	assert.Equal(t, monitor.StatePaused, sm.GetState(), "Pause should change state to paused")

	sm.Pause() // Pause when already paused
	assert.Equal(t, monitor.StatePaused, sm.GetState(), "Pause should not change state when already paused")

	sm.Start() // Start when paused
	assert.Equal(t, monitor.StatePaused, sm.GetState(), "Start should not change state when paused")

	// Finish from any state
	sm.Finish()
	assert.Equal(t, monitor.StateStopped, sm.GetState(), "Finish should change state to stopped from paused")

	sm.Start()
	sm.Finish()
	assert.Equal(t, monitor.StateStopped, sm.GetState(), "Finish should change state to stopped from running")
}

func TestSystemMonitor_FullCycle(t *testing.T) {
	sm := newTestSystemMonitor()

	// Full cycle of operations
	sm.Start()
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
	sm.Start()
	assert.Equal(t, monitor.StateRunning, sm.GetState())

	sm.Finish()
	assert.Equal(t, monitor.StateStopped, sm.GetState())
}

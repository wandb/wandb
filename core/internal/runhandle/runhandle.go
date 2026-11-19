package runhandle

import (
	"errors"
	"sync"
	"time"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/runupserter"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var (
	errInitFailed  = errors.New("runhandle: run failed to initialize")
	errInitialized = errors.New("runhandle: run already initialized")
	errNotReady    = errors.New("runhandle: run not yet initialized")
)

// RunHandle contains objects that are initialized after the first RunRecord.
//
// Code that calls the getter methods implicitly relies on only running after
// the first RunRecord is received and processed.
type RunHandle struct {
	mu sync.Mutex

	// ready is closed when Init is called for the first time.
	ready chan struct{}

	// upserter tracks and syncs some of the stream's run's metadata.
	//
	// It is nil before the run is successfully initialized.
	upserter *runupserter.RunUpserter

	// initFailed is true if the run failed to initialize.
	initFailed bool

	// unsentTelemetry is telemetry that was recorded before the run
	// was initialized.
	unsentTelemetry *spb.TelemetryRecord

	// stopwatch tracks the time elapsed since the start of the run segment.
	stopwatch Stopwatch

	// stopwatchOffset is the offset to add to the stopwatch to get the
	// `_runtime` metric.
	//
	// `_runtime` is the time since the start of the run (minus however long
	// the run was "paused", which happens in notebooks when no cells are
	// running). It is the default X axis for system metrics, and it is named
	// something like "Relative Time (Process)" in the UI.
	stopwatchOffset time.Duration
}

func New() *RunHandle {
	return &RunHandle{ready: make(chan struct{})}
}

// ReadyOrFailed returns a channel that's closed after the run has either
// initialized or failed to initialize.
func (h *RunHandle) ReadyOrFailed() <-chan struct{} {
	return h.ready
}

// UpdateTelemetry records updates to the run's telemetry.
//
// If the run is not yet initialized, the telemetry change is stored and
// applied once the run becomes initialized.
func (h *RunHandle) UpdateTelemetry(telemetry *spb.TelemetryRecord) {
	h.mu.Lock()
	defer h.mu.Unlock()

	if h.upserter != nil {
		h.upserter.UpdateTelemetry(telemetry)
		return
	}

	// If the run hasn't been initialized, buffer the telemetry to send
	// it later.
	if h.unsentTelemetry == nil {
		h.unsentTelemetry = &spb.TelemetryRecord{}
	}

	proto.Merge(h.unsentTelemetry, telemetry)
}

// Init sets the run upserter, marking the run initialized.
//
// It is an error to call this more than once or after FailInit.
func (h *RunHandle) Init(upserter *runupserter.RunUpserter) error {
	if upserter == nil {
		return errors.New("runhandle: called Init with nil upserter")
	}

	return h.initOrFail(upserter)
}

// FailInit marks the run as having failed to initialize.
//
// It does nothing if the run has already been initialized.
func (h *RunHandle) FailInit() {
	_ = h.initOrFail(nil)
}

func (h *RunHandle) initOrFail(upserter *runupserter.RunUpserter) error {
	h.mu.Lock()
	defer h.mu.Unlock()

	select {
	case <-h.ready:
		return errInitialized
	default:
	}
	close(h.ready)

	if upserter == nil {
		h.initFailed = true
		return nil
	}

	h.upserter = upserter
	h.stopwatchOffset = upserter.StartRuntime()

	if h.unsentTelemetry != nil {
		upserter.UpdateTelemetry(h.unsentTelemetry)
		h.unsentTelemetry = nil // Release memory.
	}

	return nil
}

// Upserter returns the run upserter if it has been initialized.
//
// Returns an error if no run upserter has been set or if initialization
// failed.
func (h *RunHandle) Upserter() (*runupserter.RunUpserter, error) {
	h.mu.Lock()
	defer h.mu.Unlock()

	switch {
	case h.initFailed:
		return nil, errInitFailed
	case h.upserter != nil:
		return h.upserter, nil
	default:
		return nil, errNotReady
	}
}

// StartStopwatch begins tracking elapsed time.
//
// Does nothing if the stopwatch is already started.
func (h *RunHandle) StartStopwatch() {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.stopwatch.Start()
}

// RelativeTime returns the amount of time this run segment was active.
//
// Normally this is the time since the start of the run segment.
// In notebooks, the run timer is paused when nothing is running.
func (h *RunHandle) RelativeTime() time.Duration {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.stopwatch.Elapsed()
}

// Runtime returns the `_runtime` metric for the run.
//
// This may be incorrect until the run has been initialized.
func (h *RunHandle) Runtime() time.Duration {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.stopwatch.Elapsed() + h.stopwatchOffset
}

// PauseRunTimer pauses the `_runtime` metric, preventing it from increasing.
//
// This is used in Jupyter notebooks after a cell finishes running.
func (h *RunHandle) PauseRunTimer() {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.stopwatch.Stop()
}

// ResumeRunTimer unpauses the `_runtime` metric.
//
// This is used in Jupyter notebooks before a cell starts to run.
func (h *RunHandle) ResumeRunTimer() {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.stopwatch.Start()
}

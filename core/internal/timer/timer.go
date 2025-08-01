package timer

import "time"

// Timer is used to track the run start and execution times.
type Timer struct {
	// startTime is the time the timer was started.
	startTime time.Time

	// accumulated is the time the timer has been running.
	accumulated time.Duration

	// isRunning is true if the timer is running.
	isRunning bool
}

// New creates a new timer.
func New(offset time.Duration) *Timer {
	return &Timer{
		accumulated: offset,
	}
}

// Start starts the timer with an optional offset.
// If the timer is already running, it does nothing.
func (t *Timer) Start() {
	if !t.isRunning {
		t.startTime = time.Now()
		t.isRunning = true
	}
}

// Stop stops the timer and adds the elapsed time to the accumulated time.
// If the timer is not running, it does nothing.
func (t *Timer) Stop() {
	if t.isRunning {
		elapsed := time.Since(t.startTime)
		t.accumulated += elapsed
		t.isRunning = false
	}
}

// Elapsed returns the elapsed time since the timer was started.
// If the timer is running, it returns the accumulated time plus the elapsed time.
// If the timer is not running, it returns the accumulated time.
func (t *Timer) Elapsed() time.Duration {
	if t.isRunning {
		return t.accumulated + time.Since(t.startTime)
	}
	return t.accumulated
}

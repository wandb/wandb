package scheduler

import "time"

// Clock abstracts time so tests can control it directly instead of
// waiting on real timers and grace periods.
type Clock interface {
	// Now is the current time.
	Now() time.Time

	// NewTimer starts a timer that fires once after d, and returns a
	// function to release its resources; callers must call it even if
	// the timer already fired.
	NewTimer(d time.Duration) (<-chan time.Time, func())
}

// realClock is the production Clock.
type realClock struct{}

func (realClock) Now() time.Time { return time.Now() }

func (realClock) NewTimer(d time.Duration) (<-chan time.Time, func()) {
	timer := time.NewTimer(d)
	return timer.C, func() { timer.Stop() }
}

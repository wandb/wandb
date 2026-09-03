package runhandle

import "time"

// Stopwatch measures the amount of time that it runs.
//
// The zero value is a paused stopwatch with no elapsed time.
type Stopwatch struct {
	lastStart   time.Time     // last Start() time, or zero if paused
	accumulated time.Duration // elapsed time at the last Stop()
}

// Start resumes the stopwatch.
func (s *Stopwatch) Start() {
	if !s.lastStart.IsZero() {
		return
	}

	s.lastStart = time.Now()
}

// Stop pauses the stopwatch.
func (s *Stopwatch) Stop() {
	if s.lastStart.IsZero() {
		return
	}

	s.accumulated += time.Since(s.lastStart)
	s.lastStart = time.Time{}
}

// Adjust adds `dt` to the stopwatch's elapsed time.
func (s *Stopwatch) Adjust(dt time.Duration) {
	s.accumulated += dt
}

// Elapsed returns the amount of time measured by the stopwatch.
func (s *Stopwatch) Elapsed() time.Duration {
	if s.lastStart.IsZero() {
		return s.accumulated
	} else {
		return s.accumulated + time.Since(s.lastStart)
	}
}

package filestream

import "time"

// transmitSchedule decides when the collect loop may transmit.
//
// Transmissions are spaced at least an interval apart. The interval is
// the steady-state interval until the run's first history is collected,
// when it drops to the initial interval and doubles each time it elapses
// until it is back at the steady-state interval. This uploads a run's
// first logged data quickly, no matter when it is logged.
type transmitSchedule struct {
	interval        time.Duration
	initialInterval time.Duration

	// rampStart is when the first history was collected, or zero.
	rampStart time.Time

	// last is when the schedule last allowed a transmission.
	last time.Time
}

// newTransmitSchedule returns a schedule with the given steady-state
// interval.
//
// There is no ramp if initialInterval is not positive or not less than
// interval.
func newTransmitSchedule(
	interval time.Duration,
	initialInterval time.Duration,
) *transmitSchedule {
	if initialInterval <= 0 || initialInterval > interval {
		initialInterval = interval
	}

	return &transmitSchedule{
		interval:        interval,
		initialInterval: initialInterval,
	}
}

// next returns the earliest time at which to transmit the buffered data.
func (s *transmitSchedule) next(
	now time.Time,
	buffer *FileStreamRequest,
) time.Time {
	if s.rampStart.IsZero() && len(buffer.HistoryLines) > 0 {
		s.rampStart = now
	}

	if due := s.last.Add(s.intervalAt(s.last)); due.After(now) {
		return due
	}
	return now
}

// intervalAt returns the minimum time between transmissions at time t.
func (s *transmitSchedule) intervalAt(t time.Time) time.Duration {
	if s.rampStart.IsZero() {
		return s.interval
	}

	interval, elapsed := s.initialInterval, t.Sub(s.rampStart)
	for interval < s.interval && elapsed >= interval {
		elapsed -= interval
		interval = min(2*interval, s.interval)
	}
	return interval
}

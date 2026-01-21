// Package waiting helps write testable code that sleeps.
package waiting

import (
	"sync/atomic"
	"time"
)

// Delay is a duration that some code waits for.
type Delay interface {
	// IsZero returns whether this is a zero-duration delay.
	IsZero() bool

	// Wait returns a channel that is closed after the delay elapses,
	// and a cancel function that must be used if the result is no longer
	// needed.
	Wait() (<-chan struct{}, func())
}

func NewDelay(duration time.Duration) Delay {
	return &realDelay{duration}
}

// NoDelay returns a zero delay.
func NoDelay() Delay {
	return NewDelay(0)
}

// Stopwatch is a countdown that can be reset.
type Stopwatch interface {
	// IsDone returns whether the stopwatch hit zero.
	IsDone() bool

	// Reset puts the stopwatch back at its starting time.
	Reset()

	// Wait returns a channel that is closed when the stopwatch hits zero,
	// and a cancel function that must be used if the result is no longer
	// needed.
	//
	// The channel stays open for as long as the stopwatch gets Reset.
	Wait() (<-chan struct{}, func())
}

func NewStopwatch(duration time.Duration) Stopwatch {
	s := &realStopwatch{duration, &atomic.Int64{}}
	s.Reset()
	return s
}

type realDelay struct {
	duration time.Duration
}

func (d *realDelay) IsZero() bool {
	return d.duration == 0
}

func (d *realDelay) Wait() (<-chan struct{}, func()) {
	if d.IsZero() {
		return completedDelay(), func() {}
	}

	ch := make(chan struct{})
	cancel := make(chan struct{})

	go func() {
		select {
		case <-time.After(d.duration):
		case <-cancel:
		}
		close(ch)
	}()
	return ch, func() { close(cancel) }
}

func completedDelay() <-chan struct{} {
	ch := make(chan struct{})
	close(ch)
	return ch
}

type realStopwatch struct {
	duration        time.Duration
	startTimeMicros *atomic.Int64
}

func (s *realStopwatch) IsDone() bool {
	startTime := time.UnixMicro(s.startTimeMicros.Load())
	return time.Now().After(startTime.Add(s.duration))
}

func (s *realStopwatch) Reset() {
	s.startTimeMicros.Store(time.Now().UnixMicro())
}

func (s *realStopwatch) Wait() (<-chan struct{}, func()) {
	ch := make(chan struct{})
	cancel := make(chan struct{})

	go func() {
		defer close(ch)
		for {
			originalStart := time.UnixMicro(s.startTimeMicros.Load())
			durationElapsed := time.Since(originalStart)

			select {
			case <-cancel:
				return

			case <-time.After(s.duration - durationElapsed):
			}

			if s.IsDone() {
				break
			}
		}
	}()

	return ch, func() { close(cancel) }
}

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

	// Wait returns a channel that signals after the delay elapses.
	//
	// The channel is closed after signalling once.
	Wait() <-chan struct{}
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

func (d *realDelay) Wait() <-chan struct{} {
	if d.IsZero() {
		return completedDelay()
	}

	ch := make(chan struct{}, 1)
	go func() {
		<-time.After(d.duration)
		ch <- struct{}{}
		close(ch)
	}()
	return ch
}

func completedDelay() <-chan struct{} {
	ch := make(chan struct{}, 1)
	ch <- struct{}{}
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

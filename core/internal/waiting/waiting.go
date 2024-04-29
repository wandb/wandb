// Package waiting helps write testable code that sleeps.
package waiting

import "time"

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

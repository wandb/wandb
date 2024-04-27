// Package waiting helps write testable code that sleeps.
package waiting

import "time"

// Delay is a duration that some code waits for.
type Delay interface {
	// Wait returns a channel that signals after the delay elapses.
	//
	// If the delay corresponds to a zero duration, this returns a nil channel
	// and false. Otherwise, returns true.
	//
	// The channel is closed after signalling once.
	Wait() (ch <-chan struct{}, ok bool)
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

func (d *realDelay) Wait() (<-chan struct{}, bool) {
	if d.duration == 0 {
		return nil, false
	}

	ch := make(chan struct{}, 1)
	go func() {
		<-time.After(d.duration)
		ch <- struct{}{}
		close(ch)
	}()
	return ch, true
}

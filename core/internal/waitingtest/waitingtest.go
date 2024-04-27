// Package waitingtest defines fakes for package `waiting`.
package waitingtest

import (
	"sync"

	"github.com/wandb/wandb/core/internal/waiting"
)

// FakeDelay is a fake Delay that proceeds when Tick is called.
//
// This allows controlling time in a test without resorting to `time.Sleep()`
// and hope.
type FakeDelay struct {
	cond *sync.Cond
}

func NewFakeDelay() *FakeDelay {
	return &FakeDelay{
		cond: sync.NewCond(&sync.Mutex{}),
	}
}

// Tick unblocks any goroutine that called Wait.
func (d *FakeDelay) Tick() {
	// While we hold the lock, new goroutines are blocked from calling Wait().
	d.cond.L.Lock()
	defer d.cond.L.Unlock()

	// Wakes all goroutines that called Wait() before this Tick().
	d.cond.Broadcast()
}

// Prove we implement the Delay interface.
var _ waiting.Delay = &FakeDelay{}

func (d *FakeDelay) Wait() (<-chan struct{}, bool) {
	if d == nil {
		return nil, false
	}

	d.cond.L.Lock()

	waitChan := make(chan struct{}, 1)

	go func() {
		defer d.cond.L.Unlock()
		d.cond.Wait()

		waitChan <- struct{}{}
		close(waitChan)
	}()

	return waitChan, true
}

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

	// If false, panic on the next Wait().
	allowsWait bool

	// If true, this behaves like a zero delay.
	isZero bool
}

func NewFakeDelay() *FakeDelay {
	return &FakeDelay{
		cond:       sync.NewCond(&sync.Mutex{}),
		allowsWait: true,
		isZero:     false,
	}
}

// Tick unblocks any goroutine that called Wait.
func (d *FakeDelay) Tick(allowMoreWait bool) {
	// While we hold the lock, new goroutines are blocked from calling Wait().
	d.cond.L.Lock()
	defer d.cond.L.Unlock()

	d.allowsWait = allowMoreWait

	// Wakes all goroutines that called Wait() before this Tick().
	d.cond.Broadcast()
}

// SetZero unblocks all current and future waiting goroutines.
func (d *FakeDelay) SetZero() {
	d.cond.L.Lock()
	defer d.cond.L.Unlock()

	d.isZero = true
	d.cond.Broadcast()
}

// Prove we implement the Delay interface.
var _ waiting.Delay = &FakeDelay{}

func (d *FakeDelay) IsZero() bool {
	if d == nil {
		return true
	}

	d.cond.L.Lock()
	defer d.cond.L.Unlock()
	return d.isZero
}

func (d *FakeDelay) Wait() <-chan struct{} {
	if d.IsZero() {
		return completedDelay()
	}

	d.cond.L.Lock()

	if !d.allowsWait {
		panic("tried to Wait() on a FakeDelay after the final Tick()")
	}

	waitChan := make(chan struct{}, 1)

	go func() {
		defer d.cond.L.Unlock()
		d.cond.Wait()

		waitChan <- struct{}{}
		close(waitChan)
	}()

	return waitChan
}

func completedDelay() <-chan struct{} {
	ch := make(chan struct{}, 1)
	ch <- struct{}{}
	close(ch)
	return ch
}

package waitingtest

import (
	"sync"
	"testing"
	"time"

	"github.com/wandb/wandb/core/internal/waiting"
)

// FakeDelay is a fake Delay that proceeds when Tick is called.
//
// This allows controlling time in a test without resorting to `time.Sleep()`
// and hope.
type FakeDelay struct {
	mu   *sync.Mutex
	cond *sync.Cond

	// Number of goroutines blocked in Wait().
	numWaiting     int
	numWaitingCond *sync.Cond

	// If false, panic on the next Wait().
	allowsWait bool

	// If true, this behaves like a zero delay.
	isZero bool
}

func NewFakeDelay() *FakeDelay {
	mu := &sync.Mutex{}
	return &FakeDelay{
		mu:             mu,
		cond:           sync.NewCond(mu),
		numWaitingCond: sync.NewCond(mu),
		allowsWait:     true,
		isZero:         false,
	}
}

// Tick unblocks any goroutine that called Wait.
func (d *FakeDelay) Tick(allowMoreWait bool) {
	// While we hold the lock, new goroutines are blocked from calling Wait().
	d.mu.Lock()
	defer d.mu.Unlock()

	d.allowsWait = allowMoreWait

	// Wakes all goroutines that called Wait() before this Tick().
	d.cond.Broadcast()
}

// WaitAndTick invokes Tick after at least one goroutine invokes Wait.
//
// If there are already goroutines blocked in Wait, this unblocks them
// immediately. This fails the test after a timeout.
func (d *FakeDelay) WaitAndTick(
	t *testing.T,
	allowMoreWait bool,
	timeout time.Duration) {
	d.mu.Lock()

	success := make(chan struct{})

	go func() {
		for d.numWaiting == 0 {
			d.numWaitingCond.Wait()
		}
		close(success)
		d.mu.Unlock()
		d.Tick(allowMoreWait)
	}()

	select {
	case <-success:
	case <-time.After(timeout):
		t.Fatal("no Wait() after one second in WaitAndTick()")
	}
}

// SetZero unblocks all current and future waiting goroutines.
func (d *FakeDelay) SetZero() {
	d.mu.Lock()
	defer d.mu.Unlock()

	d.isZero = true
	d.cond.Broadcast()
}

// Prove we implement the Delay interface.
var _ waiting.Delay = &FakeDelay{}

func (d *FakeDelay) IsZero() bool {
	if d == nil {
		return true
	}

	d.mu.Lock()
	defer d.mu.Unlock()
	return d.isZero
}

func (d *FakeDelay) Wait() <-chan struct{} {
	if d == nil {
		return completedDelay()
	}

	d.mu.Lock()

	if d.isZero {
		return completedDelay()
	}

	if !d.allowsWait {
		panic("tried to Wait() on a FakeDelay after the final Tick()")
	}

	waitChan := make(chan struct{}, 1)

	d.numWaiting++
	d.numWaitingCond.Signal()
	go func() {
		defer d.mu.Unlock()
		d.cond.Wait()

		d.numWaiting--

		close(waitChan)
	}()

	return waitChan
}

package waitingtest

import (
	"sync"

	"github.com/wandb/wandb/core/internal/waiting"
)

// FakeStopwatch is a Stopwatch that tests can set to Done manually.
type FakeStopwatch struct {
	sync.Mutex

	waitChan    chan struct{}
	done        bool
	doneForever bool
}

func NewFakeStopwatch() *FakeStopwatch {
	return &FakeStopwatch{}
}

// SetDone makes IsDone return true until Reset is called.
func (fs *FakeStopwatch) SetDone() {
	fs.Lock()
	defer fs.Unlock()
	fs.done = true

	if fs.waitChan != nil {
		close(fs.waitChan)
		fs.waitChan = nil
	}
}

// SetFinallyDone makes IsDone always return true even if Reset is called.
func (fs *FakeStopwatch) SetDoneForever() {
	fs.Lock()
	defer fs.Unlock()
	fs.doneForever = true

	if fs.waitChan != nil {
		close(fs.waitChan)
		fs.waitChan = nil
	}
}

// Prove we implement the interface.
var _ waiting.Stopwatch = &FakeStopwatch{}

func (fs *FakeStopwatch) IsDone() bool {
	fs.Lock()
	defer fs.Unlock()
	return fs.done || fs.doneForever
}

func (fs *FakeStopwatch) Reset() {
	fs.Lock()
	defer fs.Unlock()
	fs.done = false
}

func (fs *FakeStopwatch) Wait() <-chan struct{} {
	if fs.IsDone() {
		return completedDelay()
	}

	fs.Lock()
	defer fs.Unlock()

	if fs.waitChan == nil {
		fs.waitChan = make(chan struct{})
	}

	return fs.waitChan
}

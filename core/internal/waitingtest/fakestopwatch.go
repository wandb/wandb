package waitingtest

import (
	"sync/atomic"

	"github.com/wandb/wandb/core/internal/waiting"
)

// FakeStopwatch is a Stopwatch that tests can set to Done manually.
type FakeStopwatch struct {
	done        *atomic.Bool
	doneForever *atomic.Bool
}

func NewFakeStopwatch() *FakeStopwatch {
	return &FakeStopwatch{&atomic.Bool{}, &atomic.Bool{}}
}

// SetDone makes IsDone return true until Reset is called.
func (fs *FakeStopwatch) SetDone() {
	fs.done.Store(true)
}

// SetFinallyDone makes IsDone always return true even if Reset is called.
func (fs *FakeStopwatch) SetDoneForever() {
	fs.doneForever.Store(true)
}

// Prove we implement the interface.
var _ waiting.Stopwatch = &FakeStopwatch{}

func (fs *FakeStopwatch) IsDone() bool {
	return fs.done.Load() || fs.doneForever.Load()
}

func (fs *FakeStopwatch) Reset() {
	fs.done.Store(false)
}

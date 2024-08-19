package debounce

import (
	"github.com/wandb/wandb/core/pkg/observability"

	"golang.org/x/time/rate"
)

// Debouncer is a rate limiter that can be used to debounce events
// such as config updates.
type Debouncer struct {
	limiter       *rate.Limiter
	finished      bool
	needsDebounce bool
	logger        *observability.CoreLogger
}

// NewDebouncer creates a new debouncer
func NewDebouncer(
	eventRate rate.Limit,
	burstSize int,
	logger *observability.CoreLogger,
) *Debouncer {
	return &Debouncer{
		limiter: rate.NewLimiter(eventRate, burstSize),
		logger:  logger,
	}
}

func (d *Debouncer) SetNeedsDebounce() {
	if d == nil {
		return
	}
	d.needsDebounce = true
}

func (d *Debouncer) UnsetNeedsDebounce() {
	if d == nil {
		return
	}
	d.needsDebounce = false
}

// Debounce will call the function f if the rate limiter allows it.
func (d *Debouncer) Debounce(f func()) {
	if d == nil || d.finished {
		return
	}
	if !d.needsDebounce || !d.limiter.Allow() {
		return
	}
	d.Flush(f)
}

// Flush will call the function f if it needs to be called.
func (d *Debouncer) Flush(f func()) {
	if d == nil || d.finished {
		return
	}
	if d.needsDebounce {
		d.logger.Debug("Flushing debouncer")
		f()
		d.UnsetNeedsDebounce()
	}
}

// Stop makes all future debounce operations no-ops.
func (d *Debouncer) Stop() {
	d.finished = true
}

package debounce

import "time"

type Debouncer struct {
	debounceDuration time.Duration
	timer            *time.Timer
}

func NewDebouncer(duration time.Duration) *Debouncer {
	return &Debouncer{
		debounceDuration: duration,
	}
}

func (d *Debouncer) Debounce(f func()) {
	if d.timer != nil {
		d.timer.Stop()
	}
	d.timer = time.AfterFunc(d.debounceDuration, f)
}

func (d *Debouncer) Cancel() {
	if d.timer != nil {
		d.timer.Stop()
	}
	d.timer = nil
}

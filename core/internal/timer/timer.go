package timer

import "time"

// Timer is used to track the run start and execution times
type Timer struct {
	startTime   time.Time
	resumeTime  time.Time
	accumulated time.Duration
	isStarted   bool
	isPaused    bool
}

func New() *Timer {
	return &Timer{}
}

func (t *Timer) GetStartTimeMicro() float64 {
	return float64(t.startTime.UnixMicro()) / 1e6
}

func (t *Timer) Start(startTime *time.Time) {
	if startTime != nil {
		t.startTime = *startTime
	} else {
		t.startTime = time.Now()
	}
	t.resumeTime = t.startTime
	t.isStarted = true
}

func (t *Timer) Pause() {
	if !t.isPaused {
		elapsed := time.Since(t.resumeTime)
		t.accumulated += elapsed
		t.isPaused = true
	}
}

func (t *Timer) Resume() {
	if t.isPaused {
		t.resumeTime = time.Now()
		t.isPaused = false
	}
}

func (t *Timer) Elapsed() time.Duration {
	if !t.isStarted {
		return 0
	}
	if t.isPaused {
		return t.accumulated
	}
	return t.accumulated + time.Since(t.resumeTime)
}

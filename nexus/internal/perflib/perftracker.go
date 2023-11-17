package perflib

// PerfTracker keeps track of phases of a process.
//
// This tracker is purpose built for no allocation tracking of a process / goroutine.
//
// Why not opentelemetry?
//
//	Why not both.  This is a subset of the functionality of otel.
type PerfTracker struct {
}

func NewPerfTracker() *PerfTracker {
	return &PerfTracker{}
}

func (p *PerfTracker) Start() {
}

func (p *PerfTracker) Stop() {
}

func (p *PerfTracker) SetPhase(phase int) {
}

func (p *PerfTracker) UpdateSize(size int) {
}

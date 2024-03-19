package observability

import (
	"sync"
)

type Printer[T any] struct {
	messages []T
	mutex    sync.Mutex
}

func NewPrinter[T any]() *Printer[T] {
	return &Printer[T]{}
}

func (p *Printer[T]) Write(message T) {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	p.messages = append(p.messages, message)
}

func (p *Printer[T]) Read() []T {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	polledMessages := p.messages
	p.messages = make([]T, 0)
	return polledMessages
}

// Add this method to satisfy the interface defined by retryablehttp.Logger
// This gives the ability to use the Printer as a logger for retryablehttp.Client
// and capture responses from the retry logic
func (p *Printer[T]) Printf(_ string, args ...interface{}) {
	if len(args) > 0 {
		msg, ok := args[0].(T)
		if ok {
			p.Write(msg)
		}
	}
}

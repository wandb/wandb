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

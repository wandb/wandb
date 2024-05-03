package observability

import (
	"sync"
)

// Printer stores console messages to display to the user.
type Printer struct {
	sync.Mutex
	messages []string
}

func NewPrinter() *Printer {
	return &Printer{}
}

// Write adds a message to the console.
func (p *Printer) Write(message string) {
	p.Lock()
	defer p.Unlock()
	p.messages = append(p.messages, message)
}

// Read returns all buffered messages and clears the buffer.
func (p *Printer) Read() []string {
	p.Lock()
	defer p.Unlock()

	polledMessages := p.messages
	p.messages = make([]string, 0)

	return polledMessages
}

package observability

import (
	"sync"
)

type Printer struct {
	messages []string
	mutex    sync.Mutex
}

func NewPrinter() *Printer {
	return &Printer{}
}

func (s *Printer) Write(message string) {
	s.mutex.Lock()
	defer s.mutex.Unlock()
	s.messages = append(s.messages, message)
}

func (s *Printer) Read() []string {
	s.mutex.Lock()
	defer s.mutex.Unlock()
	polledMessages := s.messages
	s.messages = make([]string, 0)
	return polledMessages
}

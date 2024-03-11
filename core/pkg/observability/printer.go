package observability

import (
	"strings"
	"sync/atomic"
)

type Messages []string

// ForwardingService is a service for printing messages to the console, it serves
// as an aggregator for messages other services want to print. It doesn't have
// direct access to the console, it passes the messages to the client that
// have access to the console.
type ForwardingService struct {
	// requestChan is the channel for adding print requests (messages)
	requestChan chan Messages

	// pollChan is the channel for polling messages to be printed
	pollChan chan chan Messages

	// messages is the list of messages to be printed
	messages Messages

	// started is a flag to indicate if the service has been started
	started *atomic.Bool
}

// NewForwardingService returns a new PrinterService
func NewForwardingService() *ForwardingService {
	return &ForwardingService{
		requestChan: make(chan Messages, 100),
		pollChan:    make(chan chan Messages),
		started:     &atomic.Bool{},
	}
}

// Write writes a message to the printer service
func (p *ForwardingService) Write(message []byte) (int, error) {
	if p == nil {
		return 0, nil
	}
	p.requestChan <- Messages{strings.TrimSuffix(string(message), "\n")}
	return len(message), nil
}

// Poll polls the messages channel
func (p *ForwardingService) Poll() Messages {
	if p == nil {
		return nil
	}
	poll := make(chan Messages)
	p.pollChan <- poll
	return <-poll
}

// Start starts the printer service
func (p *ForwardingService) Start() {
	if p == nil {
		return
	}

	if p.started.Swap(true) {
		return
	}

	go func() {
		for {
			select {
			case msg := <-p.requestChan:
				p.messages = append(p.messages, msg...)
			case poll := <-p.pollChan:
				poll <- p.messages
				p.messages = Messages{}
			}
		}
	}()
}

// Clear the messages and the go routine
func (p *ForwardingService) Close() {
	if p == nil {
		return
	}
	close(p.requestChan)
	close(p.pollChan)
	p.messages = nil
}

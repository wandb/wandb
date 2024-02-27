package observability

import (
	"strings"
)

type Messages []string

// PrinterService is a service for printing messages
// to the console, it serves as an aggregator for messages
// other services want to print. It doesn't have direct access
// to the console, it passes the messages to the printer client
// which is responsible for printing the messages.
type PrinterService struct {
	// requestChan is the channel for requestChan to be printed
	requestChan chan Messages

	// pollChan is the channel for polling messages
	pollChan chan chan Messages

	// messages is the list of messages to be printed
	messages Messages
}

// NewPrinterService returns a new PrinterService
func NewPrinterService() *PrinterService {
	return &PrinterService{
		requestChan: make(chan Messages, 100),
		pollChan:    make(chan chan Messages),
	}
}

// Print adds a message to the messages channel
func (p *PrinterService) Write(message []byte) (int, error) {
	if p == nil {
		return 0, nil
	}
	p.requestChan <- Messages{strings.TrimSuffix(string(message), "\n")}
	return len(message), nil
}

// Poll polls the messages channel
func (p *PrinterService) Poll() Messages {
	if p == nil {
		return Messages{}
	}
	poll := make(chan Messages)
	p.pollChan <- poll
	return <-poll
}

// Start starts the printer service
func (p *PrinterService) Start() {
	if p == nil {
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

// Close closes the printer service
func (p *PrinterService) Close() {

}

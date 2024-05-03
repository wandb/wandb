package observability

import (
	"sync"
	"time"
)

// Printer stores console messages to display to the user.
type Printer struct {
	sync.Mutex
	messages []string

	// For rate-limited messages, this is the next time a message may be sent.
	rateLimits map[string]time.Time

	// getNow allows stubbing out [time.Now] in tests.
	getNow func() time.Time
}

func NewPrinter() *Printer {
	printer := &Printer{
		rateLimits: make(map[string]time.Time),
		getNow:     func() time.Time { return time.Now() },
	}

	// Occasionally clean up the rateLimits map.
	go func() {
		for {
			<-time.After(time.Minute)

			printer.Lock()
			now := printer.getNow()
			for msg, blockUntil := range printer.rateLimits {
				if now.After(blockUntil) {
					delete(printer.rateLimits, msg)
				}
			}
			printer.Unlock()
		}
	}()

	return printer
}

// Read returns all buffered messages and clears the buffer.
func (p *Printer) Read() []string {
	p.Lock()
	defer p.Unlock()

	polledMessages := p.messages
	p.messages = make([]string, 0)

	return polledMessages
}

// Write adds a message to the console.
func (p *Printer) Write(message string) {
	p.Lock()
	defer p.Unlock()
	p.messages = append(p.messages, message)
}

// AtMostEvery allows rate-limiting how often a message is printed.
//
// Usage:
//
//	printer.
//		AtMostEvery(time.Minute).
//		Write(message)
//
// Note, this doesn't affect regular `printer.Write(message)` calls.
// The duration is only checked when `AtMostEvery()` is used.
//
// This should always be used with the same duration. If the duration
// changes, the message is blocked until its last duration completes.
func (p *Printer) AtMostEvery(duration time.Duration) writeDSL {
	return writeDSL{
		printer:  p,
		duration: duration,
	}
}

type writeDSL struct {
	printer  *Printer
	duration time.Duration
}

// See [Printer.Write].
func (dsl writeDSL) Write(message string) {
	dsl.printer.Lock()
	defer dsl.printer.Unlock()

	if dsl.duration > 0 {
		blockUntil := dsl.printer.rateLimits[message]

		now := dsl.printer.getNow()
		if now.Before(blockUntil) {
			return
		}

		dsl.printer.rateLimits[message] = now.Add(dsl.duration)
	}

	dsl.printer.messages = append(dsl.printer.messages, message)
}

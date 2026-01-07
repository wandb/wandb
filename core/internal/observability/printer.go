package observability

import (
	"fmt"
	"sync"
	"time"
)

// Severity is the severity of a printed message.
//
// The integer values match Python's logging module constants for convenience.
type Severity int

const (
	Info    Severity = 20
	Warning Severity = 30
	Error   Severity = 40
)

// Printer stores console messages to display to the user.
type Printer struct {
	mu       sync.Mutex
	messages []PrinterMessage

	// For rate-limited messages, this is the next time a message may be sent.
	rateLimits map[string]time.Time

	// getNow allows stubbing out [time.Now] in tests.
	getNow func() time.Time
}

type PrinterMessage struct {
	Severity Severity
	Content  string
}

func NewPrinter() *Printer {
	printer := &Printer{
		rateLimits: make(map[string]time.Time),
		getNow:     time.Now,
	}

	// Occasionally clean up the rateLimits map.
	go func() {
		for {
			<-time.After(time.Minute)

			printer.mu.Lock()
			now := printer.getNow()
			for msg, blockUntil := range printer.rateLimits {
				if now.After(blockUntil) {
					delete(printer.rateLimits, msg)
				}
			}
			printer.mu.Unlock()
		}
	}()

	return printer
}

// Read returns all buffered messages and clears the buffer.
func (p *Printer) Read() []PrinterMessage {
	p.mu.Lock()
	defer p.mu.Unlock()

	polledMessages := p.messages
	p.messages = make([]PrinterMessage, 0)

	return polledMessages
}

// Infof writes a Sprintf-formatted message at INFO level.
func (p *Printer) Infof(format string, args ...any) {
	p.writef(Info, format, args...)
}

// Warnf writes a Sprintf-formatted message at WARNING level.
func (p *Printer) Warnf(format string, args ...any) {
	p.writef(Warning, format, args...)
}

// Errorf writes a Sprintf-formatted message at ERROR level.
func (p *Printer) Errorf(format string, args ...any) {
	p.writef(Error, format, args...)
}

// writef adds a Sprintf-formatted message to the console.
func (p *Printer) writef(severity Severity, format string, args ...any) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.messages = append(p.messages, PrinterMessage{
		Severity: severity,
		Content:  fmt.Sprintf(format, args...),
	})
}

// AtMostEvery allows rate-limiting how often a message is printed.
//
// Usage:
//
//	printer.
//		AtMostEvery(time.Minute).
//		Infof("Got number %d", dynamicNumber)
//
// The format string is used as the key for rate limiting. In the
// above example, the statement may run with different values of
// `dynamicNumber`, but a message will only be printed once a minute.
// The message severity is not part of the key.
//
// Note, this doesn't affect regular `printer.Infof(message)` and other calls.
// The duration is only checked when `AtMostEvery()` is used.
//
// This should always be used with the same duration. If the duration
// changes, the message is blocked until its last duration completes.
func (p *Printer) AtMostEvery(duration time.Duration) writeDSL {
	return writeDSL{
		printer:         p,
		rateLimitPeriod: duration,
	}
}

type writeDSL struct {
	printer         *Printer
	rateLimitPeriod time.Duration
}

// See [Printer.Infof].
func (dsl writeDSL) Infof(format string, args ...any) {
	dsl.writef(Info, format, args...)
}

// See [Printer.Warnf].
func (dsl writeDSL) Warnf(format string, args ...any) {
	dsl.writef(Warning, format, args...)
}

// See [Printer.Errorf].
func (dsl writeDSL) Errorf(format string, args ...any) {
	dsl.writef(Error, format, args...)
}

// See [Printer.writef].
func (dsl writeDSL) writef(severity Severity, format string, args ...any) {
	dsl.printer.mu.Lock()
	defer dsl.printer.mu.Unlock()

	if dsl.rateLimitPeriod > 0 {
		blockUntil := dsl.printer.rateLimits[format]

		now := dsl.printer.getNow()
		if now.Before(blockUntil) {
			return
		}

		dsl.printer.rateLimits[format] = now.Add(dsl.rateLimitPeriod)
	}

	dsl.printer.messages = append(dsl.printer.messages,
		PrinterMessage{
			Severity: severity,
			Content:  fmt.Sprintf(format, args...),
		})
}

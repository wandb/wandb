package observability

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
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
	// messages is the buffered channel of messages.
	//
	// Messages beyond the buffer limit are discarded.
	messages chan PrinterMessage

	// done is closed when the printer is closed.
	done chan struct{}

	// discarded is true if a warning about discarded messages should be
	// emitted on the next read.
	discarded atomic.Bool

	// rateLimits maps message templates to their unblock times
	// for rate limiting.
	rateLimits   map[string]time.Time
	rateLimitsMu sync.Mutex

	// getNow allows stubbing out [time.Now] in tests.
	getNow func() time.Time
}

type PrinterMessage struct {
	Severity Severity
	Content  string
}

// NewPrinter creates a new printer with the given buffer size.
//
// Messages that don't fit in the buffer are discarded.
func NewPrinter(buffer int) *Printer {
	printer := &Printer{
		messages:   make(chan PrinterMessage, buffer),
		done:       make(chan struct{}),
		rateLimits: make(map[string]time.Time),
		getNow:     time.Now,
	}

	// Occasionally clean up the rateLimits map.
	go func() {
		for {
			select {
			case <-printer.done:
				return // clean up this goroutine if the printer is done

			case <-time.After(time.Minute):
			}

			printer.rateLimitsMu.Lock()
			now := printer.getNow()
			for msg, blockUntil := range printer.rateLimits {
				if now.After(blockUntil) {
					delete(printer.rateLimits, msg)
				}
			}
			printer.rateLimitsMu.Unlock()
		}
	}()

	return printer
}

// Close closes the printer.
//
// Calling this more than once panics.
//
// This must be called to unblock calls to ReadWait().
// After this, new messages can still be added, but ReadWait() will no longer
// block to wait for them.
func (p *Printer) Close() {
	close(p.done)
}

// Read pops and returns all buffered messages.
func (p *Printer) Read() []PrinterMessage {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	return p.ReadWait(ctx)
}

// ReadWait waits for at least one message, then returns all buffered messages.
//
// It returns an empty slice only if the context ends or the printer is closed.
func (p *Printer) ReadWait(ctx context.Context) []PrinterMessage {
	var messages []PrinterMessage

	// Wait for an initial message.
	select {
	case message := <-p.messages:
		messages = append(messages, message)
	case <-p.done:
	case <-ctx.Done():
	}

loop: // Pop all buffered messages.
	for {
		select {
		case message := <-p.messages:
			messages = append(messages, message)
		default:
			break loop
		}
	}

	if p.discarded.Swap(false) {
		messages = append(messages, PrinterMessage{
			Severity: Warning,
			Content:  "Some messages exceeded the buffer and were not printed.",
		})
	}

	return messages
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
	message := PrinterMessage{
		Severity: severity,
		Content:  fmt.Sprintf(format, args...),
	}

	select {
	case p.messages <- message:
	default:
		p.discarded.Store(true)
	}
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
	if !dsl.rateLimitAllowed(format) {
		return
	}

	dsl.printer.writef(severity, format, args...)
}

// rateLimitAllowed returns whether the format string is allowed by rate limits
// to be printed, and updates its rate limits.
func (dsl writeDSL) rateLimitAllowed(format string) bool {
	if dsl.rateLimitPeriod <= 0 {
		return true
	}

	dsl.printer.rateLimitsMu.Lock()
	defer dsl.printer.rateLimitsMu.Unlock()

	blockUntil := dsl.printer.rateLimits[format]
	now := dsl.printer.getNow()
	if now.Before(blockUntil) {
		return false
	}

	dsl.printer.rateLimits[format] = now.Add(dsl.rateLimitPeriod)
	return true
}

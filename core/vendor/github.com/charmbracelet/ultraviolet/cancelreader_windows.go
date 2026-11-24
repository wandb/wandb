//go:build windows
// +build windows

package uv

import (
	"errors"
	"fmt"
	"io"
	"os"
	"sync"

	xwindows "github.com/charmbracelet/x/windows"
	"github.com/muesli/cancelreader"
	"golang.org/x/sys/windows"
)

type conInputReader struct {
	cancelMixin
	conin        windows.Handle
	originalMode uint32
	newMode      uint32

	// eventMu guards the cancel event's lifetime. Close must not free the
	// handle while a reader still waits on it: Windows reuses handle numbers
	// quickly, so the wait could land on an unrelated object. The last of
	// Close and the waiting readers frees it.
	eventMu     sync.Mutex
	cancelEvent windows.Handle
	waiters     int
	closed      bool
	eventFreed  bool
}

var _ cancelreader.CancelReader = &conInputReader{}

// NewCancelReader creates a new [cancelreader.CancelReader] that provides a
// cancelable reader interface that can be used to cancel reads.
func NewCancelReader(r io.Reader) (cancelreader.CancelReader, error) {
	fallback := func(io.Reader) (cancelreader.CancelReader, error) {
		return cancelreader.NewReader(r)
	}

	var dummy uint32
	if f, ok := r.(cancelreader.File); !ok || f.Fd() != os.Stdin.Fd() ||
		// If data was piped to the standard input, it does not emit events
		// anymore. We can detect this if the console mode cannot be set anymore,
		// in this case, we fallback to the default cancelreader implementation.
		windows.GetConsoleMode(windows.Handle(f.Fd()), &dummy) != nil {
		return fallback(r)
	}

	conin, err := windows.GetStdHandle(windows.STD_INPUT_HANDLE)
	if err != nil {
		return fallback(r)
	}

	// Discard any pending input events.
	if err := xwindows.FlushConsoleInputBuffer(conin); err != nil {
		return fallback(r)
	}

	modes := []uint32{
		windows.ENABLE_VIRTUAL_TERMINAL_INPUT,
		windows.ENABLE_WINDOW_INPUT,
		windows.ENABLE_EXTENDED_FLAGS,
	}

	originalMode, newMode, err := prepareConsole(conin, modes...)
	if err != nil {
		return nil, fmt.Errorf("failed to prepare console input: %w", err)
	}

	// Manual reset, so the event stays signaled once canceled.
	cancelEvent, err := windows.CreateEvent(nil, 1, 0, nil)
	if err != nil {
		_ = windows.SetConsoleMode(conin, originalMode)
		return nil, fmt.Errorf("create cancel event: %w", err)
	}

	return &conInputReader{
		conin:        conin,
		cancelEvent:  cancelEvent,
		originalMode: originalMode,
		newMode:      newMode,
	}, nil
}

// Cancel implements cancelreader.CancelReader.
func (r *conInputReader) Cancel() bool {
	r.setCanceled()
	r.eventMu.Lock()
	if !r.eventFreed {
		_ = windows.SetEvent(r.cancelEvent)
	}
	r.eventMu.Unlock()

	return windows.CancelIoEx(r.conin, nil) == nil || windows.CancelIo(r.conin) == nil
}

// Close implements cancelreader.CancelReader. It is safe to call more than
// once, and with a reader still waiting for input.
func (r *conInputReader) Close() error {
	r.setCanceled()

	r.eventMu.Lock()
	if r.closed {
		r.eventMu.Unlock()
		return nil
	}
	r.closed = true
	// Wake a reader that may still wait on the cancel event. Close can be
	// called without Cancel.
	_ = windows.SetEvent(r.cancelEvent)
	// With a reader still waiting, that reader frees the event when it
	// wakes. Otherwise nothing else holds it.
	freeNow := r.waiters == 0
	if freeNow {
		r.eventFreed = true
	}
	r.eventMu.Unlock()

	var errs []error
	if r.originalMode != 0 {
		if err := windows.SetConsoleMode(r.conin, r.originalMode); err != nil {
			errs = append(errs, fmt.Errorf("reset console mode: %w", err))
		}
	}

	if freeNow {
		if err := windows.CloseHandle(r.cancelEvent); err != nil {
			errs = append(errs, fmt.Errorf("close cancel event: %w", err))
		}
	}

	return errors.Join(errs...)
}

// waitForInput blocks until the console has input or the reader is canceled
// or closed. While it waits, Close leaves the cancel event alone, and if Close
// ran meanwhile, the wait frees the event on its way out.
func (r *conInputReader) waitForInput() error {
	r.eventMu.Lock()
	if r.closed {
		r.eventMu.Unlock()
		return cancelreader.ErrCanceled
	}
	r.waiters++
	event := r.cancelEvent
	r.eventMu.Unlock()

	_, err := windows.WaitForMultipleObjects([]windows.Handle{r.conin, event}, false, windows.INFINITE)

	r.eventMu.Lock()
	r.waiters--
	if r.closed && r.waiters == 0 && !r.eventFreed {
		r.eventFreed = true
		_ = windows.CloseHandle(event)
	}
	r.eventMu.Unlock()

	return err
}

// Read implements cancelreader.CancelReader.
func (r *conInputReader) Read(data []byte) (int, error) {
	if r.isCanceled() {
		return 0, cancelreader.ErrCanceled
	}

	var n uint32
	if err := windows.ReadFile(r.conin, data, &n, nil); err != nil {
		return int(n), fmt.Errorf("read console input: %w", err)
	}

	return int(n), nil
}

func prepareConsole(input windows.Handle, modes ...uint32) (originalMode, newMode uint32, err error) {
	err = windows.GetConsoleMode(input, &originalMode)
	if err != nil {
		return 0, 0, fmt.Errorf("get console mode: %w", err)
	}

	for _, mode := range modes {
		newMode |= mode
	}

	err = windows.SetConsoleMode(input, newMode)
	if err != nil {
		return 0, 0, fmt.Errorf("set console mode: %w", err)
	}

	return originalMode, newMode, nil
}

// cancelMixin represents a goroutine-safe cancelation status.
type cancelMixin struct {
	unsafeCanceled bool
	lock           sync.Mutex
}

func (c *cancelMixin) setCanceled() {
	c.lock.Lock()
	defer c.lock.Unlock()

	c.unsafeCanceled = true
}

func (c *cancelMixin) isCanceled() bool {
	c.lock.Lock()
	defer c.lock.Unlock()

	return c.unsafeCanceled
}

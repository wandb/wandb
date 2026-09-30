// Package kittyshm provides named pixel buffers for Kitty shared-memory frames.
package kittyshm

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"sync/atomic"
)

// ErrUnsupported indicates that this process has no shared-memory transport.
var ErrUnsupported = errors.New("kitty shared memory is unsupported")

// Object is a named buffer. The terminal consumes it when it reads the APC;
// producers must Unlink objects for frames that are dropped before transmission.
type Object struct {
	Name   string
	Size   int
	unlink func() error
	retire func()
	done   atomic.Bool
}

// Unlink removes the object. Calling it after consumption or more than once is safe.
func (o *Object) Unlink() error {
	if o == nil || o.unlink == nil {
		return nil
	}
	err := o.unlink()
	if err == nil {
		o.done.Store(true)
	}
	return err
}

// Retire releases a submitted frame once the terminal has consumed it. Browser
// entries can be removed immediately; native readers get time to drain the tty.
func (o *Object) Retire() {
	if o == nil || o.Done() {
		return
	}
	if o.retire != nil {
		o.retire()
	} else {
		_ = o.Unlink()
	}
}

// Done reports whether producer-side cleanup has finished.
func (o *Object) Done() bool { return o == nil || o.done.Load() }

func newName() string {
	var b [10]byte
	_, _ = rand.Read(b[:])
	return "/ntc-" + hex.EncodeToString(b[:])
}

package httputils

import (
	"bytes"
	"io"
)

// MaxBodyBytes is the maximum number of bytes the SDK captures from an HTTP
// body for attaching to events or spans. Bodies larger than this are dropped
// rather than truncated, to avoid invalid partial structured payloads.
const MaxBodyBytes = 10 * 1024

// ReadCloser combines an io.Reader and an io.Closer to implement io.ReadCloser.
type ReadCloser struct {
	io.Reader
	io.Closer
}

// LimitedBuffer is like a bytes.Buffer, but limited to store at most Capacity
// bytes. Any writes past the capacity are silently discarded, similar to
// io.Discard.
type LimitedBuffer struct {
	Capacity int

	bytes.Buffer
	overflow bool
}

// NewLimitedBuffer returns a LimitedBuffer with the given capacity.
func NewLimitedBuffer(capacity int) *LimitedBuffer {
	return &LimitedBuffer{Capacity: capacity}
}

// NewLimitedBufferFromBytes returns a LimitedBuffer initialized from b.
func NewLimitedBufferFromBytes(capacity int, b []byte) *LimitedBuffer {
	buf := NewLimitedBuffer(capacity)
	if len(b) > capacity {
		buf.overflow = true
		b = b[:capacity]
	}
	buf.Buffer = *bytes.NewBuffer(b)
	return buf
}

// Write implements io.Writer.
func (b *LimitedBuffer) Write(p []byte) (n int, err error) {
	originalLen := len(p)
	if b.overflow {
		return originalLen, nil
	}
	left := b.Capacity - b.Len()
	if left < 0 {
		left = 0
	}
	if len(p) > left {
		b.overflow = true
		p = p[:left]
	}
	_, err = b.Buffer.Write(p)
	return originalLen, err
}

// Overflow returns true if the LimitedBuffer discarded bytes written to it.
func (b *LimitedBuffer) Overflow() bool {
	return b.overflow
}

// ReadBody reads up to MaxBodyBytes from r and returns the bytes read.
func ReadBody(r io.Reader) []byte {
	if r == nil {
		return nil
	}
	data, err := io.ReadAll(io.LimitReader(r, MaxBodyBytes+1))
	if err != nil || len(data) == 0 || len(data) > MaxBodyBytes {
		return nil
	}
	return data
}

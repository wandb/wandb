package schedulertest

import (
	"testing"
	"time"
)

// ReceiveTimeout bounds a wait for a value the code under test should
// produce almost immediately.
const ReceiveTimeout = 2 * time.Second

// Receive returns the next value sent on ch, failing the test if none
// arrives within ReceiveTimeout.
//
// Tests that hand a poll to a goroutine collect its answer with this
// instead of a bare receive: a scheduler that never answers then fails
// its test in seconds, naming the channel it hung on, rather than
// stalling until the whole package times out.
//
// Receive also returns at once from a closed channel, so it doubles as a
// bounded wait for a signal a test goroutine closes.
func Receive[T any](t testing.TB, ch <-chan T) T {
	t.Helper()

	select {
	case value := <-ch:
		return value
	case <-time.After(ReceiveTimeout):
		t.Fatalf("timed out after %s waiting to receive", ReceiveTimeout)
		var zero T
		return zero
	}
}

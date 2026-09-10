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

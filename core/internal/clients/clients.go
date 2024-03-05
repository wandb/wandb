// Deprecated package providing utilities for defining HTTP clients.
package clients

import (
	"time"
)

func SecondsToDuration(seconds float64) time.Duration {
	return time.Duration(seconds * float64(time.Second))
}

func DurationToSeconds(duration time.Duration) float64 {
	return float64(duration) / float64(time.Second)
}

package api

import (
	"net/http"
	"strconv"
	"time"
)

// Blocks until we don't need to rate-limit requests.
func (backend *Backend) waitIfRateLimited() {
	backend.isRateLimitedCond.L.Lock()
	defer backend.isRateLimitedCond.L.Unlock()

	for backend.isRateLimited {
		backend.isRateLimitedCond.Wait()
	}
}

// Processes rate-limiting headers from the server response.
func (backend *Backend) processRateLimitHeaders(response *http.Response) {
	remainingStr := response.Header.Get("RateLimit-Remaining")
	resetStr := response.Header.Get("RateLimit-Reset")

	if len(remainingStr) == 0 || len(resetStr) == 0 {
		return // Missing relevant headers.
	}

	remaining, err := strconv.ParseInt(remainingStr, 10, 64)
	if err != nil || remaining > 0 {
		// Bad string, or we're not out of quota yet.
		return
	}

	resetSeconds, err := strconv.ParseInt(resetStr, 10, 64)
	if err != nil {
		return
	}

	// If the server sends rate-limits using the wrong units, don't hang
	// the whole program.
	const maxDuration = time.Duration(30) * time.Second
	resetDuration := time.Duration(resetSeconds) * time.Second
	if resetDuration > maxDuration {
		resetDuration = maxDuration
	}

	backend.markRateLimitedFor(resetDuration)
}

// Marks us as rate-limited for the given duration.
//
// At the end of the duration, wakes all goroutines blocked on
// [waitIfRateLimited].
func (backend *Backend) markRateLimitedFor(duration time.Duration) {
	backend.isRateLimitedCond.L.Lock()
	defer backend.isRateLimitedCond.L.Unlock()

	if !backend.isRateLimited {
		backend.isRateLimited = true

		go func() {
			time.Sleep(duration)

			backend.isRateLimitedCond.L.Lock()
			backend.isRateLimited = false
			backend.isRateLimitedCond.L.Unlock()

			backend.isRateLimitedCond.Broadcast()
		}()
	}

}

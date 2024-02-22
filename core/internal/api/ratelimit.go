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

	backend.markRateLimitedFor(time.Duration(resetSeconds) * time.Second)
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

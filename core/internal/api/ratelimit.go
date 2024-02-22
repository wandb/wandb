package api

import (
	"fmt"
	"log/slog"
	"net/http"
	"strconv"
	"sync"
	"time"
)

// Book-keeping for rate-limiting. Accessed only in this file.
type rateLimiter struct {
	// Whether the backend is currently rate-limiting us.
	//
	// Only read/write this while isRateLimitedCond is locked.
	isRateLimited bool

	// Condvar for waiting for isRateLimited to become false.
	isRateLimitedCond *sync.Cond

	// Logger for rate-limiting information.
	logger *slog.Logger
}

func newRateLimiter(logger *slog.Logger) rateLimiter {
	return rateLimiter{
		isRateLimited:     false,
		isRateLimitedCond: sync.NewCond(&sync.Mutex{}),
		logger:            logger,
	}
}

// Blocks until we don't need to rate-limit requests.
func (ratelimit *rateLimiter) waitIfRateLimited() {
	ratelimit.isRateLimitedCond.L.Lock()
	defer ratelimit.isRateLimitedCond.L.Unlock()

	for ratelimit.isRateLimited {
		ratelimit.isRateLimitedCond.Wait()
	}
}

// Processes rate-limiting headers from the server response.
func (ratelimit *rateLimiter) processRateLimitHeaders(response *http.Response) {
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

	ratelimit.markRateLimitedFor(resetDuration)
}

// Marks us as rate-limited for the given duration.
//
// At the end of the duration, wakes all goroutines blocked on
// [waitIfRateLimited].
func (ratelimit *rateLimiter) markRateLimitedFor(duration time.Duration) {
	ratelimit.isRateLimitedCond.L.Lock()
	defer ratelimit.isRateLimitedCond.L.Unlock()

	if ratelimit.isRateLimited {
		return
	}

	ratelimit.logger.Debug(fmt.Sprintf("api: rate limiting for %v", duration))
	ratelimit.isRateLimited = true

	go func() {
		time.Sleep(duration)

		ratelimit.isRateLimitedCond.L.Lock()
		ratelimit.isRateLimited = false
		ratelimit.isRateLimitedCond.L.Unlock()

		ratelimit.isRateLimitedCond.Broadcast()
	}()
}

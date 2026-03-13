package observability

import (
	"crypto/md5"
	"time"

	lru "github.com/hashicorp/golang-lru"
)

// CaptureRateLimiter limits the rate at which messages are uploaded to Sentry.
//
// It maps message hashes to timestamps. The last capture time of every message
// is tracked and capturing is skipped for messages seen too recently.
//
// Memory usage is limited with an LRU cache. If the cache is too small
// and too many different types of errors are logged frequently, repeated
// messages may still get through.
//
// A nil value lets all messages through.
type CaptureRateLimiter struct {
	cache       *lru.Cache
	minDuration time.Duration
}

// NewCaptureRateLimiter returns a new CaptureRateLimiter using a cache
// of the given size and rate limiting each message to once per minDuration.
func NewCaptureRateLimiter(
	size int,
	minDuration time.Duration,
) (*CaptureRateLimiter, error) {
	cache, err := lru.New(size)
	if err != nil {
		return nil, err
	}

	return &CaptureRateLimiter{cache, minDuration}, nil
}

// AllowCapture returns true if a message should be captured and if so, updates
// the message's last capture time to now.
func (rl *CaptureRateLimiter) AllowCapture(msg string) bool {
	if rl == nil {
		return true
	}

	h := md5.New()
	h.Write([]byte(msg))
	hash := string(h.Sum(nil))

	lastSent, inCache := rl.cache.Get(hash)

	now := time.Now()
	if inCache && now.Sub(lastSent.(time.Time)) < rl.minDuration {
		return false
	}

	rl.cache.Add(hash, now)
	return true
}

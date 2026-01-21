package sentry_ext

import (
	"crypto/md5"
	"encoding/hex"
	"time"

	lru "github.com/hashicorp/golang-lru"
)

const (
	recentErrorDuration = time.Minute * 5
	defaultCacheSize    = 100
)

type cache struct {
	*lru.Cache
}

// newCache creates a new cache
func newCache(size int) (*cache, error) {
	if size == 0 {
		size = defaultCacheSize
	}
	c, err := lru.New(size)
	if err != nil {
		return nil, err
	}
	return &cache{c}, nil
}

// shouldCapture returns true if the error should be captured
//
// This function uses an LRU cache to track the last time an error was sent to
// Sentry. If the error was sent recently, it will return false to skip sending
// the error.
func (c *cache) shouldCapture(err error) bool {
	// Generate a hash of the error message
	h := md5.New()
	h.Write([]byte(err.Error()))
	hash := hex.EncodeToString(h.Sum(nil))

	now := time.Now()
	if lastSent, exists := c.Get(hash); exists {
		if now.Sub(lastSent.(time.Time)) < recentErrorDuration {
			return false // Skip sending the error if it's too recent
		}
	}

	// Update the timestamp for the error
	c.Add(hash, now)
	return true
}

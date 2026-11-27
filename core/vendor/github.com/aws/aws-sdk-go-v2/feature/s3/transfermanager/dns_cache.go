package transfermanager

import (
	"sync"
	"time"

	"github.com/aws/smithy-go/container/private/cache"
	"github.com/aws/smithy-go/container/private/cache/lru"
)

// dnsCache implements an LRU cache of DNS query results by host.
//
// Cache retrievals will automatically rotate between IP addresses for
// multi-value query results.
type dnsCache struct {
	mu    sync.Mutex
	addrs cache.Cache
}

// newDNSCache returns an initialized dnsCache with given capacity.
func newDNSCache(cap int) *dnsCache {
	return &dnsCache{
		addrs: lru.New(cap),
	}
}

// GetAddr returns the next IP address for the given host if present in the
// cache.
func (c *dnsCache) GetAddr(host string) (string, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()

	v, ok := c.addrs.Get(host)
	if !ok {
		return "", false
	}

	record := v.(*dnsCacheEntry)
	if timeNow().After(record.expires) {
		return "", false
	}

	addr := record.addrs[record.index]
	record.index = (record.index + 1) % len(record.addrs)
	return addr, true
}

// PutAddrs stores a DNS query result in the cache, overwriting any present
// entry for the host if it exists.
func (c *dnsCache) PutAddrs(host string, addrs []string, expires time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.addrs.Put(host, &dnsCacheEntry{addrs, expires, 0})
}

type dnsCacheEntry struct {
	addrs   []string
	expires time.Time
	index   int
}

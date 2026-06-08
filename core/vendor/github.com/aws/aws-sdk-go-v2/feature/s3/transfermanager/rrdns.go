package transfermanager

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/internal/sync/singleflight"
)

var timeNow = time.Now

// WithRoundRobinDNS configures an http.Transport to spread HTTP connections
// across multiple IP addresses for a given host.
//
// This is recommended by the [S3 performance guide] in high-concurrency
// application environments.
//
// WithRoundRobinDNS wraps the underlying DialContext hook on http.Transport.
// Future modifications to this hook MUST preserve said wrapping in order for
// round-robin DNS to operate.
//
// [S3 performance guide]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance-design-patterns.html
func WithRoundRobinDNS(opts ...func(*RoundRobinDNSOptions)) func(*http.Transport) {
	options := &RoundRobinDNSOptions{
		TTL:      30 * time.Second,
		MaxHosts: 100,
	}
	for _, opt := range opts {
		opt(options)
	}

	return func(t *http.Transport) {
		rr := &rrDNS{
			cache:       newDNSCache(options.MaxHosts),
			expiry:      options.TTL,
			resolver:    &net.Resolver{},
			dialContext: t.DialContext,
		}
		t.DialContext = rr.DialContext
	}
}

// RoundRobinDNSOptions configures use of round-robin DNS.
type RoundRobinDNSOptions struct {
	// The length of time for which the results of a DNS query are valid.
	TTL time.Duration

	// A limit to the number of DNS query results, cached by hostname, which are
	// stored. Round-robin DNS uses an LRU cache.
	MaxHosts int
}

type resolver interface {
	LookupHost(context.Context, string) ([]string, error)
}

type rrDNS struct {
	sf    singleflight.Group
	cache *dnsCache

	expiry   time.Duration
	resolver resolver

	dialContext func(ctx context.Context, network, addr string) (net.Conn, error)
}

// DialContext implements the DialContext hook used by http.Transport,
// pre-caching IP addresses for a given host and distributing them evenly
// across new connections.
func (r *rrDNS) DialContext(ctx context.Context, network, addr string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		return nil, fmt.Errorf("rrdns split host/port: %w", err)
	}

	ipaddr, err := r.getAddr(ctx, host)
	if err != nil {
		return nil, fmt.Errorf("rrdns lookup host: %w", err)
	}

	return r.dialContext(ctx, network, net.JoinHostPort(ipaddr, port))
}

func (r *rrDNS) getAddr(ctx context.Context, host string) (string, error) {
	addr, ok := r.cache.GetAddr(host)
	if ok {
		return addr, nil
	}
	return r.lookupHost(ctx, host)
}

func (r *rrDNS) lookupHost(ctx context.Context, host string) (string, error) {
	ch := r.sf.DoChan(host, func() (any, error) {
		addrs, err := r.resolver.LookupHost(ctx, host)
		if err != nil {
			return nil, err
		}

		expires := timeNow().Add(r.expiry)
		r.cache.PutAddrs(host, addrs, expires)
		return nil, nil
	})

	select {
	case result := <-ch:
		if result.Err != nil {
			return "", result.Err
		}

		addr, _ := r.cache.GetAddr(host)
		return addr, nil
	case <-ctx.Done():
		return "", ctx.Err()
	}
}

// WithRotoDialer configures an http.Transport to cycle through multiple local
// network addresses when creating new HTTP connections.
//
// WithRotoDialer REPLACES the root DialContext hook on the underlying
// Transport, thereby destroying any previously-applied wrappings around it. If
// the caller needs to apply additional decorations to the DialContext hook,
// they must do so after applying WithRotoDialer.
func WithRotoDialer(addrs []net.Addr) func(*http.Transport) {
	return func(t *http.Transport) {
		var dialers []*net.Dialer
		for _, addr := range addrs {
			dialers = append(dialers, &net.Dialer{
				LocalAddr: addr,
			})
		}

		t.DialContext = (&rotoDialer{
			dialers: dialers,
		}).DialContext
	}
}

type rotoDialer struct {
	mu      sync.Mutex
	dialers []*net.Dialer
	index   int
}

func (r *rotoDialer) DialContext(ctx context.Context, network, addr string) (net.Conn, error) {
	return r.next().DialContext(ctx, network, addr)
}

func (r *rotoDialer) next() *net.Dialer {
	r.mu.Lock()
	defer r.mu.Unlock()

	d := r.dialers[r.index]
	r.index = (r.index + 1) % len(r.dialers)
	return d
}

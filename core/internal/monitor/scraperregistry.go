package monitor

import (
	"context"
	"fmt"
	"math"
	"strings"
	"sync"
	"time"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ScraperRegistry shares the OpenMetrics and DCGM exporter scrapers of a
// process between its runs.
//
// Runs that read the same endpoint with the same headers and filters get one
// scraper, which runs at the smallest of their sampling intervals and hands
// each scrape, or its error, to each run once.
type ScraperRegistry struct {
	// mu guards scrapers and the fields of each sharedScraper.
	mu       sync.Mutex
	scrapers map[string]*sharedScraper
}

func NewScraperRegistry() *ScraperRegistry {
	return &ScraperRegistry{scrapers: map[string]*sharedScraper{}}
}

// OpenMetrics returns the shared Resource for an OpenMetrics endpoint, or nil
// if it cannot be created.
//
// The Resource has a Close method that must be called when the run is done.
func (r *ScraperRegistry) OpenMetrics(
	logger *observability.CoreLogger,
	name string,
	url string,
	filters *spb.OpenMetricsFilters,
	headers map[string]string,
	interval time.Duration,
) Resource {
	filtersKey, _ := proto.MarshalOptions{Deterministic: true}.Marshal(filters)
	key := strings.Join(
		[]string{"openmetrics", name, url, fmt.Sprint(headers), string(filtersKey)},
		"\x00",
	)
	return r.share(key, interval, func() Resource {
		if om := NewOpenMetrics(logger, name, url, filters, headers, nil); om != nil {
			return om
		}
		return nil
	})
}

// DCGMExporter returns the shared Resource for a DCGM exporter, or nil if it
// cannot be created.
//
// The Resource has a Close method that must be called when the run is done.
func (r *ScraperRegistry) DCGMExporter(
	params DCGMExporterParams,
	interval time.Duration,
) Resource {
	key := strings.Join(
		[]string{"dcgm_exporter", params.URL, fmt.Sprint(params.Headers)},
		"\x00",
	)
	return r.share(key, interval, func() Resource {
		if de := NewDCGMExporter(params); de != nil {
			return de
		}
		return nil
	})
}

// share subscribes to the scraper for key, creating it from newResource
// if it does not exist. A nil registry shares nothing.
func (r *ScraperRegistry) share(
	key string,
	interval time.Duration,
	newResource func() Resource,
) Resource {
	if r == nil {
		return newResource()
	}
	r.mu.Lock()
	defer r.mu.Unlock()

	if s, ok := r.scrapers[key]; ok {
		return s.subscribe(interval)
	}

	resource := newResource()
	if resource == nil {
		return nil
	}
	ctx, cancel := context.WithCancel(context.Background())
	s := &sharedScraper{
		registry:    r,
		key:         key,
		resource:    resource,
		cancel:      cancel,
		wakeCh:      make(chan struct{}, 1),
		subscribers: map[*scraperSubscriber]time.Duration{},
	}
	r.scrapers[key] = s
	sub := s.subscribe(interval)
	go s.loop(ctx)
	return sub
}

// sharedScraper scrapes one Resource for any number of subscribers.
type sharedScraper struct {
	registry *ScraperRegistry
	key      string
	resource Resource
	cancel   context.CancelFunc

	// wakeCh tells loop to scrape now and pick up the current interval.
	wakeCh chan struct{}

	// subscribers maps each subscriber to its sampling interval.
	subscribers map[*scraperSubscriber]time.Duration

	// interval is the smallest of the subscribers' intervals.
	interval time.Duration

	// latest and latestErr are the outcome of the last scrape and seq is
	// its sequence number.
	latest    *spb.StatsRecord
	latestErr error
	seq       uint64
}

// subscribe adds a subscriber that samples every interval. It receives
// the scrapes made after it joined, starting with one made right away.
//
// registry.mu must be held.
func (s *sharedScraper) subscribe(interval time.Duration) *scraperSubscriber {
	sub := &scraperSubscriber{scraper: s, seen: s.seq}
	s.subscribers[sub] = interval
	s.setInterval()
	s.wake()
	return sub
}

// unsubscribe removes sub, stopping the scraper if it was the last subscriber.
func (s *sharedScraper) unsubscribe(sub *scraperSubscriber) {
	s.registry.mu.Lock()
	defer s.registry.mu.Unlock()

	if _, ok := s.subscribers[sub]; !ok {
		return
	}
	delete(s.subscribers, sub)
	if len(s.subscribers) == 0 {
		s.cancel()
		delete(s.registry.scrapers, s.key)
		return
	}
	s.setInterval()
}

// setInterval recomputes interval and wakes loop if it changed.
//
// registry.mu must be held.
func (s *sharedScraper) setInterval() {
	interval := time.Duration(math.MaxInt64)
	for _, i := range s.subscribers {
		interval = min(interval, i)
	}
	if interval != s.interval {
		s.interval = interval
		s.wake()
	}
}

func (s *sharedScraper) wake() {
	select {
	case s.wakeCh <- struct{}{}:
	default:
	}
}

func (s *sharedScraper) currentInterval() time.Duration {
	s.registry.mu.Lock()
	defer s.registry.mu.Unlock()
	return s.interval
}

// loop scrapes the resource once per interval until ctx is done.
func (s *sharedScraper) loop(ctx context.Context) {
	ticker := time.NewTicker(s.currentInterval())
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-s.wakeCh:
			ticker.Reset(s.currentInterval())
		case <-ticker.C:
		}

		record, err := scrape(s.resource)
		if len(record.GetItem()) == 0 && err == nil {
			continue
		}
		s.registry.mu.Lock()
		s.latest, s.latestErr = record, err
		s.seq++
		s.registry.mu.Unlock()
	}
}

// scrape samples the resource, turning a panic into an error.
func scrape(r Resource) (record *spb.StatsRecord, err error) {
	defer func() {
		if p := recover(); p != nil {
			err = fmt.Errorf("monitor: panic sampling: %v", p)
		}
	}()
	return r.Sample()
}

// scraperSubscriber is a run's view of a sharedScraper.
type scraperSubscriber struct {
	scraper *sharedScraper

	// seen is the seq of the last record returned by Sample.
	seen uint64
}

// Sample returns the latest scrape not yet returned by this subscriber, or
// nil if there is none.
func (sub *scraperSubscriber) Sample() (*spb.StatsRecord, error) {
	s := sub.scraper
	s.registry.mu.Lock()
	defer s.registry.mu.Unlock()

	if sub.seen == s.seq {
		return nil, nil
	}
	sub.seen = s.seq
	if s.latest == nil {
		return nil, s.latestErr
	}
	return proto.Clone(s.latest).(*spb.StatsRecord), s.latestErr
}

// Probe probes the shared resource.
func (sub *scraperSubscriber) Probe(ctx context.Context) *spb.EnvironmentRecord {
	return sub.scraper.resource.Probe(ctx)
}

// Close ends the subscription, stopping the scraper if it was the last one.
func (sub *scraperSubscriber) Close() {
	sub.scraper.unsubscribe(sub)
}

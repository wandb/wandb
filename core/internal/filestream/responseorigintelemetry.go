package filestream

import (
	"strconv"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/observability"
)

// Telemetry events for retrying 404s that lack the server's response-origin
// header. See RetryPolicy.
//
// Something in front of the W&B server sends these 404s, so the server never
// sees them. These events are the only way to tell whether the retries help.
//
// Each event is a counter and a log record. The log record carries the
// details: how long the 404s lasted and how many there were.
//
// Telemetry is sent in batches to the same W&B server, through the same
// load balancer or proxy. A batch sent while that is failing is dropped, so
// no event is recorded while the request is still getting these 404s:
// outcomes that mean the server answered again are recorded at once, and a
// deadline that ran out is recorded when the filestream finishes.
const (
	// eventUnmarked404Recovered counts requests that retried header-less 404s
	// and then succeeded, even if other retried failures came in between.
	eventUnmarked404Recovered = "filestream_unmarked_404_recovered"

	// eventUnmarked404DeadlineExceeded counts requests whose unbroken run of
	// header-less 404s outlasted the deadline, which stops uploads.
	//
	// It is recorded when the filestream finishes. See deferredTelemetry.
	eventUnmarked404DeadlineExceeded = "filestream_unmarked_404_deadline_exceeded"

	// eventUnmarked404StoppedByServer counts requests that retried header-less
	// 404s and then got a 404 from the server itself, which stops uploads.
	eventUnmarked404StoppedByServer = "filestream_unmarked_404_stopped_by_server"
)

// logRetryStarted logs the first header-less 404 a request retries.
//
// It is not sent as telemetry: the 404s mean the server is likely
// unreachable, so the event would likely be dropped.
func (s *unmarked404Retry) logRetryStarted() {
	s.logger.Warn(
		"filestream: got a 404 without the server's response-origin"+
			" header, likely from a load balancer or proxy; retrying",
		"header", api.ServerHeader,
		"deadline", s.deadline)
}

// logStreakRestarted logs header-less 404s that resumed after a different
// response, which restarts the deadline.
func (s *unmarked404Retry) logStreakRestarted() {
	s.logger.Warn(
		"filestream: 404s without the server's response-origin header"+
			" resumed after a different response; retrying with a new deadline",
		"header", api.ServerHeader,
		"deadline", s.deadline,
		"since_first", time.Since(s.firstRetryAt),
		"unmarked_404s", s.retriedCount)
}

// recordRecovered reports a successful upload after header-less 404s.
func (s *unmarked404Retry) recordRecovered() {
	elapsed := time.Since(s.firstRetryAt)
	s.logger.Info(
		"filestream: upload succeeded after 404s without the server's"+
			" response-origin header",
		"after", elapsed,
		"unmarked_404s", s.retriedCount)
	s.logger.RecordTelemetry(
		eventUnmarked404Recovered,
		s.attributes(elapsed, s.retriedCount),
	)
}

// recordDeadlineExceeded reports giving up on header-less 404s.
//
// The 404s are still arriving, so the telemetry waits for the filestream
// to finish.
func (s *unmarked404Retry) recordDeadlineExceeded() {
	elapsed := time.Since(s.streakStart)
	s.logger.Error(
		"filestream: 404s without the server's response-origin header"+
			" lasted past the deadline; stopping",
		"elapsed", elapsed,
		"deadline", s.deadline,
		"unmarked_404s", s.streakLength)
	s.deferred.add(
		eventUnmarked404DeadlineExceeded,
		s.attributes(elapsed, s.streakLength),
	)
}

// recordStoppedByServer reports a server 404 after header-less 404s.
func (s *unmarked404Retry) recordStoppedByServer() {
	elapsed := time.Since(s.firstRetryAt)
	s.logger.Warn(
		"filestream: got a 404 from the server after 404s from"+
			" something in front of it; stopping",
		"after", elapsed,
		"unmarked_404s", s.retriedCount)
	s.logger.RecordTelemetry(
		eventUnmarked404StoppedByServer,
		s.attributes(elapsed, s.retriedCount),
	)
}

// attributes describes header-less 404s for an outcome event.
//
// Recovery and server stops count from the request's first such 404; the
// deadline counts only the unbroken run that exceeded it.
func (s *unmarked404Retry) attributes(
	elapsed time.Duration,
	count int,
) map[string]string {
	return map[string]string{
		"duration_seconds": wholeSeconds(elapsed),
		"unmarked_404s":    strconv.Itoa(count),
		"deadline_seconds": wholeSeconds(s.deadline),
	}
}

// wholeSeconds formats a duration as a whole number of seconds.
func wholeSeconds(d time.Duration) string {
	return strconv.FormatInt(int64(d/time.Second), 10)
}

// deferredTelemetry holds telemetry events to record when the filestream
// finishes instead of right away.
//
// An event recorded while the server is unreachable is likely dropped,
// because telemetry goes to the same server. Waiting until the end of the
// run gives the outage time to end, after which the stream sends pending
// telemetry before it shuts down. The events are still lost if the outage
// outlasts the run or the process exits without finishing the filestream.
//
// The zero value is ready to use.
type deferredTelemetry struct {
	mu     sync.Mutex
	events []deferredEvent
}

type deferredEvent struct {
	name       string
	attributes map[string]string
}

// add queues an event.
func (d *deferredTelemetry) add(name string, attributes map[string]string) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.events = append(d.events, deferredEvent{name, attributes})
}

// flush records and forgets the queued events.
func (d *deferredTelemetry) flush(logger *observability.CoreLogger) {
	d.mu.Lock()
	events := d.events
	d.events = nil
	d.mu.Unlock()

	for _, event := range events {
		logger.RecordTelemetry(event.name, event.attributes)
	}
}

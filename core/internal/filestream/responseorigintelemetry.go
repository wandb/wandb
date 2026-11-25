package filestream

import (
	"strconv"
	"time"

	"github.com/wandb/wandb/core/internal/api"
)

// Telemetry events for retrying 404s that lack the server's response-origin
// header. See RetryPolicy.
//
// Something in front of the W&B server sends these 404s, so the server never
// sees them. These events are the only way to tell whether the retries help.
//
// Each event is a counter and a log record. The log record carries the
// details: how long the 404s lasted and how many there were.
const (
	// eventUnmarked404RetryStarted counts requests that started retrying
	// header-less 404s.
	//
	// Each such request later records at most one of the other events.
	eventUnmarked404RetryStarted = "filestream_unmarked_404_retry_started"

	// eventUnmarked404Recovered counts requests that retried header-less 404s
	// and then succeeded, even if other retried failures came in between.
	eventUnmarked404Recovered = "filestream_unmarked_404_recovered"

	// eventUnmarked404DeadlineExceeded counts requests whose unbroken run of
	// header-less 404s outlasted the deadline, which stops uploads.
	eventUnmarked404DeadlineExceeded = "filestream_unmarked_404_deadline_exceeded"

	// eventUnmarked404StoppedByServer counts requests that retried header-less
	// 404s and then got a 404 from the server itself, which stops uploads.
	eventUnmarked404StoppedByServer = "filestream_unmarked_404_stopped_by_server"
)

// recordRetryStarted reports the first header-less 404 a request retries.
func (s *unmarked404Retry) recordRetryStarted() {
	s.logger.Warn(
		"filestream: got a 404 without the server's response-origin"+
			" header, likely from a load balancer or proxy; retrying",
		"header", api.ServerHeader,
		"deadline", s.deadline)
	s.logger.RecordTelemetry(eventUnmarked404RetryStarted, map[string]string{
		"deadline_seconds": wholeSeconds(s.deadline),
	})
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
func (s *unmarked404Retry) recordDeadlineExceeded() {
	elapsed := time.Since(s.streakStart)
	s.logger.Error(
		"filestream: 404s without the server's response-origin header"+
			" lasted past the deadline; stopping",
		"elapsed", elapsed,
		"deadline", s.deadline,
		"unmarked_404s", s.streakLength)
	s.logger.RecordTelemetry(
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

package http

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"sync"
	"time"

	"github.com/getsentry/sentry-go/internal/debuglog"
	"github.com/getsentry/sentry-go/internal/protocol"
	"github.com/getsentry/sentry-go/internal/ratelimit"
	"github.com/getsentry/sentry-go/internal/util"
	"github.com/getsentry/sentry-go/report"
)

const (
	apiVersion = 7

	defaultTimeout           = time.Second * 30
	defaultQueueSize         = 1000
	defaultClientReportsTick = time.Second * 30
)

var (
	ErrTransportQueueFull = errors.New("transport queue full")
	ErrTransportClosed    = errors.New("transport is closed")
	ErrEmptyEnvelope      = errors.New("empty envelope provided")
)

type TransportOptions struct {
	Dsn           string
	HTTPClient    *http.Client
	HTTPTransport http.RoundTripper
	HTTPProxy     string
	HTTPSProxy    string
	CaCerts       *x509.CertPool
	Recorder      report.ClientReportRecorder
	Provider      report.ClientReportProvider
}

func getProxyConfig(options TransportOptions) func(*http.Request) (*url.URL, error) {
	if len(options.HTTPSProxy) > 0 {
		return func(*http.Request) (*url.URL, error) {
			return url.Parse(options.HTTPSProxy)
		}
	}

	if len(options.HTTPProxy) > 0 {
		return func(*http.Request) (*url.URL, error) {
			return url.Parse(options.HTTPProxy)
		}
	}

	return http.ProxyFromEnvironment
}

func getTLSConfig(options TransportOptions) *tls.Config {
	if options.CaCerts != nil {
		return &tls.Config{
			RootCAs:    options.CaCerts,
			MinVersion: tls.VersionTLS12,
		}
	}

	return nil
}

func getSentryRequestFromEnvelope(ctx context.Context, dsn *protocol.Dsn, envelope *protocol.Envelope) (r *http.Request, err error) {
	defer func() {
		if r != nil {
			sdkName := envelope.Header.Sdk.Name
			sdkVersion := envelope.Header.Sdk.Version

			r.Header.Set("User-Agent", fmt.Sprintf("%s/%s", sdkName, sdkVersion))
			r.Header.Set("Content-Type", "application/x-sentry-envelope")

			auth := fmt.Sprintf("Sentry sentry_version=%d, "+
				"sentry_client=%s/%s, sentry_key=%s", apiVersion, sdkName, sdkVersion, dsn.GetPublicKey())

			if dsn.GetSecretKey() != "" {
				auth = fmt.Sprintf("%s, sentry_secret=%s", auth, dsn.GetSecretKey())
			}

			r.Header.Set("X-Sentry-Auth", auth)
		}
	}()

	var buf bytes.Buffer
	_, err = envelope.WriteTo(&buf)
	if err != nil {
		return nil, err
	}

	return http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		dsn.GetAPIURL().String(),
		&buf,
	)
}

func categoryFromEnvelope(envelope *protocol.Envelope) ratelimit.Category {
	if envelope == nil || len(envelope.Items) == 0 {
		return ratelimit.CategoryAll
	}

	for _, item := range envelope.Items {
		if item == nil || item.Header == nil {
			continue
		}

		switch item.Header.Type {
		case protocol.EnvelopeItemTypeEvent:
			return ratelimit.CategoryError
		case protocol.EnvelopeItemTypeTransaction:
			return ratelimit.CategoryTransaction
		case protocol.EnvelopeItemTypeCheckIn:
			return ratelimit.CategoryMonitor
		case protocol.EnvelopeItemTypeLog:
			return ratelimit.CategoryLog
		case protocol.EnvelopeItemTypeAttachment:
			continue
		default:
			return ratelimit.CategoryAll
		}
	}

	return ratelimit.CategoryAll
}

// SyncTransport is a blocking implementation of Transport.
//
// Clients using this transport will send requests to Sentry sequentially and
// block until a response is returned.
//
// The blocking behavior is useful in a limited set of use cases. For example,
// use it when deploying code to a Function as a Service ("Serverless")
// platform, where any work happening in a background goroutine is not
// guaranteed to execute.
//
// For most cases, prefer AsyncTransport.
type SyncTransport struct {
	dsn       *protocol.Dsn
	client    *http.Client
	transport http.RoundTripper
	recorder  report.ClientReportRecorder
	provider  report.ClientReportProvider

	mu     sync.Mutex
	limits ratelimit.Map

	Timeout time.Duration
}

func NewSyncTransport(options TransportOptions) protocol.TelemetryTransport {
	dsn, err := protocol.NewDsn(options.Dsn)
	if err != nil || dsn == nil {
		debuglog.Printf("Transport is disabled: invalid dsn: %v\n", err)
		return NewNoopTransport()
	}

	recorder := options.Recorder
	if recorder == nil {
		recorder = report.NoopRecorder()
	}
	provider := options.Provider
	if provider == nil {
		provider = report.NoopProvider()
	}

	transport := &SyncTransport{
		Timeout:  defaultTimeout,
		limits:   make(ratelimit.Map),
		dsn:      dsn,
		recorder: recorder,
		provider: provider,
	}

	if options.HTTPTransport != nil {
		transport.transport = options.HTTPTransport
	} else {
		transport.transport = &http.Transport{
			Proxy:           getProxyConfig(options),
			TLSClientConfig: getTLSConfig(options),
		}
	}

	if options.HTTPClient != nil {
		transport.client = options.HTTPClient
	} else {
		transport.client = &http.Client{
			Transport: transport.transport,
			Timeout:   transport.Timeout,
		}
	}

	return transport
}

func (t *SyncTransport) SendEnvelope(envelope *protocol.Envelope) error {
	return t.SendEnvelopeWithContext(context.Background(), envelope)
}

func (t *SyncTransport) Close() {}

func (t *SyncTransport) IsRateLimited(category ratelimit.Category) bool {
	return t.disabled(category)
}

func (t *SyncTransport) HasCapacity() bool { return true }

func (t *SyncTransport) SendEnvelopeWithContext(ctx context.Context, envelope *protocol.Envelope) error {
	if envelope == nil || len(envelope.Items) == 0 {
		return ErrEmptyEnvelope
	}

	category := categoryFromEnvelope(envelope)
	if t.disabled(category) {
		t.recorder.RecordForEnvelope(report.ReasonRateLimitBackoff, envelope)
		return nil
	}
	// the sync transport needs to attach client reports when available
	t.provider.AttachToEnvelope(envelope)

	request, err := getSentryRequestFromEnvelope(ctx, t.dsn, envelope)
	if err != nil {
		debuglog.Printf("There was an issue creating the request: %v", err)
		t.recorder.RecordForEnvelope(report.ReasonInternalError, envelope)
		return err
	}
	identifier := util.EnvelopeIdentifier(envelope)
	debuglog.Printf(
		"Sending %s to %s project: %s",
		identifier,
		t.dsn.GetHost(),
		t.dsn.GetProjectID(),
	)

	result, err := util.DoSendRequest(t.client, request, identifier)
	if err != nil {
		debuglog.Printf("There was an issue with sending an event: %v", err)
		t.recorder.RecordForEnvelope(report.ReasonNetworkError, envelope)
		return err
	}
	if result.IsSendError() {
		t.recorder.RecordForEnvelope(report.ReasonSendError, envelope)
	}

	t.mu.Lock()
	t.limits.Merge(result.Limits)
	t.mu.Unlock()

	return nil
}

func (t *SyncTransport) Flush(_ time.Duration) bool {
	return true
}

func (t *SyncTransport) FlushWithContext(_ context.Context) bool {
	return true
}

func (t *SyncTransport) disabled(c ratelimit.Category) bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	disabled := t.limits.IsRateLimited(c)
	if disabled {
		debuglog.Printf("Too many requests for %q, backing off till: %v", c, t.limits.Deadline(c))
	}
	return disabled
}

// AsyncTransport is the default, non-blocking, implementation of Transport.
//
// Clients using this transport will enqueue requests in a queue and return to
// the caller before any network communication has happened. Requests are sent
// to Sentry sequentially from a background goroutine.
type AsyncTransport struct {
	dsn       *protocol.Dsn
	client    *http.Client
	transport http.RoundTripper
	recorder  report.ClientReportRecorder
	provider  report.ClientReportProvider

	queue chan *protocol.Envelope

	mu     sync.RWMutex
	limits ratelimit.Map

	done chan struct{}
	wg   sync.WaitGroup

	flushRequest chan chan struct{}

	QueueSize int
	Timeout   time.Duration

	startOnce sync.Once
	closeOnce sync.Once
}

func NewAsyncTransport(options TransportOptions) protocol.TelemetryTransport {
	dsn, err := protocol.NewDsn(options.Dsn)
	if err != nil || dsn == nil {
		debuglog.Printf("Transport is disabled: invalid dsn: %v", err)
		return NewNoopTransport()
	}

	recorder := options.Recorder
	if recorder == nil {
		recorder = report.NoopRecorder()
	}
	provider := options.Provider
	if provider == nil {
		provider = report.NoopProvider()
	}

	transport := &AsyncTransport{
		QueueSize: defaultQueueSize,
		Timeout:   defaultTimeout,
		done:      make(chan struct{}),
		limits:    make(ratelimit.Map),
		dsn:       dsn,
		recorder:  recorder,
		provider:  provider,
	}

	transport.queue = make(chan *protocol.Envelope, transport.QueueSize)
	transport.flushRequest = make(chan chan struct{})

	if options.HTTPTransport != nil {
		transport.transport = options.HTTPTransport
	} else {
		transport.transport = &http.Transport{
			Proxy:           getProxyConfig(options),
			TLSClientConfig: getTLSConfig(options),
		}
	}

	if options.HTTPClient != nil {
		transport.client = options.HTTPClient
	} else {
		transport.client = &http.Client{
			Transport: transport.transport,
			Timeout:   transport.Timeout,
		}
	}

	transport.start()
	return transport
}

func (t *AsyncTransport) start() {
	t.startOnce.Do(func() {
		if t.recorder == nil {
			t.recorder = report.NoopRecorder()
		}
		if t.provider == nil {
			t.provider = report.NoopProvider()
		}
		t.wg.Add(1)
		go t.worker()
	})
}

// HasCapacity reports whether the async transport queue appears to have space
// for at least one more envelope. This is a best-effort, non-blocking check.
func (t *AsyncTransport) HasCapacity() bool {
	t.mu.RLock()
	defer t.mu.RUnlock()
	select {
	case <-t.done:
		return false
	default:
	}
	return len(t.queue) < cap(t.queue)
}

func (t *AsyncTransport) SendEnvelope(envelope *protocol.Envelope) error {
	select {
	case <-t.done:
		return ErrTransportClosed
	default:
	}

	if envelope == nil || len(envelope.Items) == 0 {
		return ErrEmptyEnvelope
	}

	category := categoryFromEnvelope(envelope)
	if t.isRateLimited(category) {
		t.recorder.RecordForEnvelope(report.ReasonRateLimitBackoff, envelope)
		return nil
	}

	select {
	case t.queue <- envelope:
		identifier := util.EnvelopeIdentifier(envelope)
		debuglog.Printf(
			"Sending %s to %s project: %s",
			identifier,
			t.dsn.GetHost(),
			t.dsn.GetProjectID(),
		)
		return nil
	default:
		t.recorder.RecordForEnvelope(report.ReasonQueueOverflow, envelope)
		return ErrTransportQueueFull
	}
}

func (t *AsyncTransport) Flush(timeout time.Duration) bool {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	return t.FlushWithContext(ctx)
}

func (t *AsyncTransport) FlushWithContext(ctx context.Context) bool {
	flushResponse := make(chan struct{})
	select {
	case t.flushRequest <- flushResponse:
		select {
		case <-flushResponse:
			debuglog.Println("Buffer flushed successfully.")
			return true
		case <-ctx.Done():
			debuglog.Println("Failed to flush, buffer timed out.")
			return false
		}
	case <-ctx.Done():
		debuglog.Println("Failed to flush, buffer timed out.")
		return false
	}
}

func (t *AsyncTransport) Close() {
	t.closeOnce.Do(func() {
		close(t.done)
		close(t.queue)
		close(t.flushRequest)
		t.wg.Wait()
	})
}

func (t *AsyncTransport) IsRateLimited(category ratelimit.Category) bool {
	return t.isRateLimited(category)
}

func (t *AsyncTransport) worker() {
	defer t.wg.Done()

	crTicker := time.NewTicker(defaultClientReportsTick)
	defer crTicker.Stop()

	for {
		select {
		case <-t.done:
			return
		case <-crTicker.C:
			t.sendClientReport()
		case envelope, open := <-t.queue:
			if !open {
				return
			}
			t.sendEnvelopeHTTP(envelope)
		case flushResponse, open := <-t.flushRequest:
			if !open {
				return
			}
			t.drainQueue()
			close(flushResponse)
		}
	}
}

// sendClientReport sends a standalone envelope containing only a client report.
func (t *AsyncTransport) sendClientReport() {
	r := t.provider.TakeReport()
	if r == nil {
		return
	}
	item, err := r.ToEnvelopeItem()
	if err != nil {
		debuglog.Printf("Failed to serialize client report: %v", err)
		return
	}
	header := &protocol.EnvelopeHeader{
		SentAt: time.Now(),
		Dsn:    t.dsn.String(),
	}
	envelope := protocol.NewEnvelope(header)
	envelope.AddItem(item)

	ctx, cancel := context.WithTimeout(context.Background(), defaultTimeout)
	defer cancel()

	request, err := getSentryRequestFromEnvelope(ctx, t.dsn, envelope)
	if err != nil {
		debuglog.Printf("Failed to create client report request: %v", err)
		return
	}
	result, err := util.DoSendRequest(t.client, request, "client report")
	if err != nil {
		debuglog.Printf("Failed to send client report: %v", err)
		return
	}

	t.mu.Lock()
	t.limits.Merge(result.Limits)
	t.mu.Unlock()
}

func (t *AsyncTransport) drainQueue() {
	for {
		select {
		case envelope, open := <-t.queue:
			if !open {
				return
			}
			t.sendEnvelopeHTTP(envelope)
		default:
			return
		}
	}
}

func (t *AsyncTransport) sendEnvelopeHTTP(envelope *protocol.Envelope) bool { //nolint: unparam
	category := categoryFromEnvelope(envelope)
	if t.isRateLimited(category) {
		t.recorder.RecordForEnvelope(report.ReasonRateLimitBackoff, envelope)
		return false
	}
	// attach to envelope after rate-limit check
	t.provider.AttachToEnvelope(envelope)

	ctx, cancel := context.WithTimeout(context.Background(), defaultTimeout)
	defer cancel()

	request, err := getSentryRequestFromEnvelope(ctx, t.dsn, envelope)
	if err != nil {
		debuglog.Printf("Failed to create request from envelope: %v", err)
		t.recorder.RecordForEnvelope(report.ReasonInternalError, envelope)
		return false
	}

	identifier := util.EnvelopeIdentifier(envelope)
	result, err := util.DoSendRequest(t.client, request, identifier)
	if err != nil {
		debuglog.Printf("HTTP request failed: %v", err)
		t.recorder.RecordForEnvelope(report.ReasonNetworkError, envelope)
		return false
	}
	if result.IsSendError() {
		t.recorder.RecordForEnvelope(report.ReasonSendError, envelope)
	}

	t.mu.Lock()
	t.limits.Merge(result.Limits)
	t.mu.Unlock()

	return result.Success
}

func (t *AsyncTransport) isRateLimited(category ratelimit.Category) bool {
	t.mu.RLock()
	defer t.mu.RUnlock()
	limited := t.limits.IsRateLimited(category)
	if limited {
		debuglog.Printf("Rate limited for category %q until %v", category, t.limits.Deadline(category))
	}
	return limited
}

// NoopTransport is a transport implementation that drops all events.
// Used internally when an empty or invalid DSN is provided.
type NoopTransport struct{}

func NewNoopTransport() *NoopTransport {
	debuglog.Println("Transport initialized with invalid DSN. Using NoopTransport. No events will be delivered.")
	return &NoopTransport{}
}

func (t *NoopTransport) SendEnvelope(_ *protocol.Envelope) error {
	debuglog.Println("Envelope dropped due to NoopTransport usage.")
	return nil
}

func (t *NoopTransport) IsRateLimited(_ ratelimit.Category) bool {
	return false
}

func (t *NoopTransport) Flush(_ time.Duration) bool {
	return true
}

func (t *NoopTransport) FlushWithContext(_ context.Context) bool {
	return true
}

func (t *NoopTransport) Close() {
	// Nothing to close
}

func (t *NoopTransport) HasCapacity() bool { return true }

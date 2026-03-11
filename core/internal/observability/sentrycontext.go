package observability

import (
	"sync"
	"time"

	"github.com/getsentry/sentry-go"
)

// SentryContext is a mutex-protected [sentry.Hub] that allows derived loggers
// to share Sentry tags.
type SentryContext struct {
	mu  sync.Mutex
	hub *sentry.Hub
}

// NewSentryContext creates a new SentryContext cloning the given hub.
//
// The hub must not be nil.
func NewSentryContext(hub *sentry.Hub) *SentryContext {
	if hub == nil {
		panic("observability: NewSentryContext: nil hub")
	}

	hub = hub.Clone()
	hub.Scope().AddEventProcessor(RemoveLoggerFrames)
	return &SentryContext{hub: hub}
}

// AddTags mutates the base tags for this context.
//
// Holds the mutex.
func (sc *SentryContext) AddTags(tags map[string]string) {
	sc.mu.Lock()
	defer sc.mu.Unlock()
	sc.hub.Scope().SetTags(tags)
}

// SetUser mutates the User for this context.
//
// Holds the mutex.
func (sc *SentryContext) SetUser(user sentry.User) {
	sc.mu.Lock()
	defer sc.mu.Unlock()
	sc.hub.Scope().SetUser(user)
}

// WithScope pushes a new scope on the hub's stack and runs the function.
//
// The scope can be accessed with `hub.Scope()` and is safe to mutate,
// for instance to set tags. Modifications to the scope only last until
// the function returns.
//
// Holds the mutex.
func (sc *SentryContext) WithScope(fn func(hub *sentry.Hub)) {
	sc.mu.Lock()
	defer sc.mu.Unlock()

	sc.hub.PushScope()
	defer sc.hub.PopScope()
	fn(sc.hub)
}

// Flush flushes the Sentry hub.
//
// Does not hold the mutex because this does not mutate the hub.
func (sc *SentryContext) Flush(timeout time.Duration) bool {
	return sc.hub.Flush(timeout)
}

package sentry

import (
	"context"
	"sync"
	"time"
)

// MockScope implements [Scope] for use in tests.
type MockScope struct {
	breadcrumb      *Breadcrumb
	shouldDropEvent bool
}

func (scope *MockScope) AddBreadcrumb(breadcrumb *Breadcrumb, _ int) {
	scope.breadcrumb = breadcrumb
}

func (scope *MockScope) ApplyToEvent(event *Event, _ *EventHint, _ *Client) *Event {
	if scope.shouldDropEvent {
		return nil
	}
	return event
}

// MockTransport implements [Transport] for use in tests.
type MockTransport struct {
	mu        sync.Mutex
	events    []*Event
	lastEvent *Event
}

func (t *MockTransport) Configure(_ ClientOptions) {}
func (t *MockTransport) SendEvent(event *Event) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.events = append(t.events, event)
	t.lastEvent = event
}
func (t *MockTransport) Flush(_ time.Duration) bool {
	return true
}
func (t *MockTransport) FlushWithContext(_ context.Context) bool { return true }
func (t *MockTransport) Events() []*Event {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.events
}
func (t *MockTransport) Close() {}

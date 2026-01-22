package mailbox

import (
	"context"
	"sync"
)

// Mailbox is used to process cancel requests from the client.
// For example, if the run initialization times out, the client
// sends a cancel request, which then cancels the context for the run
// so that all in-flight network requests are cancelled.
type Mailbox struct {
	mu sync.Mutex

	mb map[string]context.CancelFunc
}

func New() *Mailbox {
	return &Mailbox{
		mb: make(map[string]context.CancelFunc),
	}
}

func (m *Mailbox) Add(ctx context.Context, cancel context.CancelFunc, key string) context.Context {
	if cancel == nil {
		ctx, cancel = context.WithCancel(ctx)
	}
	m.mu.Lock()
	m.mb[key] = cancel
	m.mu.Unlock()
	return ctx
}

func (m *Mailbox) Cancel(key string) {
	if cancel, ok := m.mb[key]; ok {
		cancel()
		m.mu.Lock()
		delete(m.mb, key)
		m.mu.Unlock()
	}
}

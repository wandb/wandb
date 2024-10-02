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
	mb map[string]context.CancelFunc
	*sync.Mutex
}

func New() *Mailbox {
	return &Mailbox{
		mb:    make(map[string]context.CancelFunc),
		Mutex: &sync.Mutex{},
	}
}

func (m *Mailbox) Add(ctx context.Context, cancel context.CancelFunc, key string) context.Context {
	if cancel == nil {
		ctx, cancel = context.WithCancel(ctx)
	}
	m.Lock()
	m.mb[key] = cancel
	m.Unlock()
	return ctx
}

func (m *Mailbox) Cancel(key string) {
	if cancel, ok := m.mb[key]; ok {
		cancel()
		m.Lock()
		delete(m.mb, key)
		m.Unlock()
	}
}

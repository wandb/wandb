package runconsolelogs

import (
	"context"
	"sync"

	"github.com/wandb/wandb/core/internal/sparselist"
	"golang.org/x/time/rate"
)

// debouncedWriter buffers and rate limits line modifications.
type debouncedWriter struct {
	mu  sync.Mutex
	wg  sync.WaitGroup
	ctx context.Context

	isFlushing bool
	flush      func(sparselist.SparseList[*RunLogsLine])
	rateLimit  *rate.Limiter

	buffer sparselist.SparseList[*RunLogsLine]
}

// NewDebouncedWriter creates a writer that buffers changes and invokes flush
// with the specified rate limit.
//
// Stops invoking `flush` after the context is cancelled.
func NewDebouncedWriter(
	rateLimit *rate.Limiter,
	ctx context.Context,
	flush func(sparselist.SparseList[*RunLogsLine]),
) *debouncedWriter {
	return &debouncedWriter{
		ctx:       ctx,
		flush:     flush,
		rateLimit: rateLimit,
	}
}

func (b *debouncedWriter) OnChanged(lineNum int, line *RunLogsLine) {
	b.mu.Lock()
	defer b.mu.Unlock()

	b.buffer.Put(lineNum, line.Clone())

	if !b.isFlushing {
		b.isFlushing = true

		b.wg.Add(1)
		go func() {
			b.loopFlushBuffer()
			b.wg.Done()
		}()
	}
}

func (b *debouncedWriter) loopFlushBuffer() {
	for {
		err := b.rateLimit.Wait(b.ctx)
		if err != nil {
			// Cancelled or deadline exceeded.
			return
		}

		b.mu.Lock()

		if b.buffer.Len() == 0 {
			b.isFlushing = false
			b.mu.Unlock()
			return
		}

		lines := b.buffer
		b.buffer = sparselist.SparseList[*RunLogsLine]{}
		b.mu.Unlock()

		b.flush(lines)
	}
}

func (b *debouncedWriter) Wait() {
	b.wg.Wait()
}

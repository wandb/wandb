package runconsolelogs

import (
	"context"
	"sync"

	"golang.org/x/time/rate"

	"github.com/wandb/wandb/core/internal/sparselist"
)

// debouncedWriter buffers and rate limits line modifications.
type debouncedWriter struct {
	mu sync.Mutex
	wg sync.WaitGroup

	rateLimitCtx    context.Context // context for debouncing
	cancelRateLimit func()          // cancels rateLimitCtx to flush changes

	isFlushing bool
	flush      func(*sparselist.SparseList[*RunLogsLine])
	rateLimit  *rate.Limiter

	buffer *sparselist.SparseList[*RunLogsLine]
}

// NewDebouncedWriter creates a writer that buffers changes and invokes flush
// with the specified rate limit.
//
// Stops invoking `flush` after the context is cancelled.
func NewDebouncedWriter(
	rateLimit *rate.Limiter,
	flush func(*sparselist.SparseList[*RunLogsLine]),
) *debouncedWriter {
	rateLimitCtx, cancelRateLimit := context.WithCancel(context.Background())

	return &debouncedWriter{
		rateLimitCtx:    rateLimitCtx,
		cancelRateLimit: cancelRateLimit,

		flush:     flush,
		rateLimit: rateLimit,
		buffer:    &sparselist.SparseList[*RunLogsLine]{},
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
		// An error happens only if the context is canceled, in which case
		// we stop rate limiting.
		_ = b.rateLimit.Wait(b.rateLimitCtx)

		b.mu.Lock()

		if b.buffer.Len() == 0 {
			b.isFlushing = false
			b.mu.Unlock()
			return
		}

		lines := b.buffer
		b.buffer = &sparselist.SparseList[*RunLogsLine]{}
		b.mu.Unlock()

		b.flush(lines)
	}
}

func (b *debouncedWriter) Finish() {
	b.cancelRateLimit()
	b.wg.Wait()
}

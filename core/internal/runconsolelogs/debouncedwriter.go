package runconsolelogs

import (
	"context"
	"sync"

	"github.com/wandb/wandb/core/internal/sparselist"
	"golang.org/x/time/rate"
)

// debouncedWriter buffers and rate limits line modifications.
type debouncedWriter struct {
	mu sync.Mutex
	wg sync.WaitGroup

	isFlushing bool
	flush      func(sparselist.SparseList[RunLogsLine])
	rateLimit  *rate.Limiter

	buffer sparselist.SparseList[RunLogsLine]
}

func NewDebouncedWriter(
	rateLimit *rate.Limiter,
	flush func(sparselist.SparseList[RunLogsLine]),
) *debouncedWriter {
	return &debouncedWriter{
		flush:     flush,
		rateLimit: rateLimit,
	}
}

func (b *debouncedWriter) OnChanged(lineNum int, line RunLogsLine) {
	b.mu.Lock()
	defer b.mu.Unlock()

	b.buffer.Put(lineNum, line)

	if !b.isFlushing {
		b.isFlushing = true

		b.wg.Add(1)
		go func() {
			for {
				// Errors are not possible.
				_ = b.rateLimit.Wait(context.Background())

				b.mu.Lock()

				if b.buffer.Len() == 0 {
					// Exit the loop while holding the lock, so that the
					// buffer cannot change in the meantime.
					break
				}

				lines := b.buffer
				b.buffer = sparselist.SparseList[RunLogsLine]{}
				b.mu.Unlock()

				b.flush(lines)
			}

			b.isFlushing = false
			b.wg.Done()
			b.mu.Unlock()
		}()
	}
}

func (b *debouncedWriter) Wait() {
	b.wg.Wait()
}

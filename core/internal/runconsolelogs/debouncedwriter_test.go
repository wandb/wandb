package runconsolelogs_test

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/internal/runconsolelogs"
	"github.com/wandb/wandb/core/internal/sparselist"
	"golang.org/x/time/rate"
)

func TestInvokesCallback(t *testing.T) {
	flushes := make(chan sparselist.SparseList[*RunLogsLine], 1)
	writer := NewDebouncedWriter(
		rate.NewLimiter(rate.Inf, 1),
		context.Background(),
		func(lines sparselist.SparseList[*RunLogsLine]) {
			flushes <- lines
		},
	)

	line := &RunLogsLine{}
	line.Content = []rune("content")
	writer.OnChanged(1, line)
	writer.Wait()

	select {
	case lines := <-flushes:
		lineActual, _ := lines.Get(1)
		assert.Equal(t, "content", string(lineActual.Content))
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}

func TestRespectsCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	flushes := make(chan sparselist.SparseList[*RunLogsLine], 1)
	writer := NewDebouncedWriter(
		rate.NewLimiter(rate.Inf, 1),
		ctx,
		func(lines sparselist.SparseList[*RunLogsLine]) {
			flushes <- lines
		},
	)

	cancel()
	writer.OnChanged(1, &RunLogsLine{})
	writer.Wait()

	select {
	case <-flushes:
		t.Error("writer flushed despite being cancelled")
	default:
	}
}

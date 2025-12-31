package runconsolelogs_test

import (
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	. "github.com/wandb/wandb/core/internal/runconsolelogs"
	"github.com/wandb/wandb/core/internal/sparselist"
	"golang.org/x/time/rate"
)

func TestDebouncesAndInvokesCallback(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		var flushes []*sparselist.SparseList[*RunLogsLine]
		writer := NewDebouncedWriter(
			rate.NewLimiter(rate.Every(time.Second), 1),
			func(lines *sparselist.SparseList[*RunLogsLine]) {
				flushes = append(flushes, lines)
			},
		)

		writer.OnChanged(1, RunLogsLineForTest("content 1"))
		writer.OnChanged(2, RunLogsLineForTest("content 2"))
		time.Sleep(2 * time.Second) // flushes after the debounce period expires
		writer.OnChanged(3, RunLogsLineForTest("content 3"))
		writer.Finish() // flushes immediately

		require.Len(t, flushes, 2)
		assert.Equal(t,
			map[int]string{1: "content 1", 2: "content 2"},
			sparselist.Map(flushes[0], (*RunLogsLine).ContentAsString).ToMap())
		assert.Equal(t,
			map[int]string{3: "content 3"},
			sparselist.Map(flushes[1], (*RunLogsLine).ContentAsString).ToMap())
	})
}

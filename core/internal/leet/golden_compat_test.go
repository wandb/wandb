package leet_test

import (
	"io"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
)

// TestLevelDBHistorySource_GoldenFixturesStepAxis reads each pinned golden
// fixture through LevelDBHistorySource and asserts the x-axis leet uses for
// charting matches the fixture's intended step semantics.
func TestLevelDBHistorySource_GoldenFixturesStepAxis(t *testing.T) {
	cases := []struct {
		name  string
		wantX []float64
	}{
		{name: "old_auto_steps", wantX: []float64{0, 1, 2}},
		{name: "new_auto_steps", wantX: []float64{0, 1, 2}},
		{name: "old_explicit_steps", wantX: []float64{0, 5, 10}},
		{name: "new_explicit_steps", wantX: []float64{0, 5, 10}},
		{name: "old_resumed_run", wantX: []float64{5, 6, 7}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			path := transactionlogtest.GoldenLogPath(t, tc.name)
			src, err := leet.NewLevelDBHistorySource(
				path, observability.NewNoOpLogger())
			require.NoError(t, err)
			defer src.Close()

			var gotX []float64
			for {
				msg, err := src.Read(leet.BootLoadChunkSize, leet.BootLoadMaxTime)
				if err != nil && !assert.ErrorIs(t, err, io.EOF) {
					break
				}
				batch, ok := msg.(leet.ChunkedBatchMsg)
				require.True(t, ok)
				for _, batchMsg := range batch.Msgs {
					hist, ok := batchMsg.(leet.HistoryMsg)
					if !ok {
						continue
					}
					metric, ok := hist.Metrics["x"]
					if !ok {
						continue
					}
					gotX = append(gotX, metric.X...)
				}
				if err != nil {
					break
				}
				if !batch.HasMore {
					time.Sleep(10 * time.Millisecond)
				}
			}

			assert.Equal(t, tc.wantX, gotX)
		})
	}
}

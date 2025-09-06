package filetransfer

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestSplitWorkerTasks(t *testing.T) {
	t.Run("even distribution", func(t *testing.T) {
		// 6 parts, 2 workers -> each worker gets 3 parts
		tasks, err := SplitWorkerTasks(6, 2)
		require.NoError(t, err)
		require.Len(t, tasks, 2)

		assert.Equal(t, 0, tasks[0].Start) // inclusive
		assert.Equal(t, 3, tasks[0].End)   // exclusive

		assert.Equal(t, 3, tasks[1].Start)
		assert.Equal(t, 6, tasks[1].End)
	})

	t.Run("uneven distribution", func(t *testing.T) {
		// 11 parts, 3 workers -> 2 workers get 4 parts, 1 worker gets 3 parts
		tasks, err := SplitWorkerTasks(11, 3)
		require.NoError(t, err)
		require.Len(t, tasks, 3)

		// Worker 0: parts [0 ,4) (4 parts) - large worker
		assert.Equal(t, 0, tasks[0].Start)
		assert.Equal(t, 4, tasks[0].End)

		// Worker 1: parts [4, 8) (4 parts) - large worker
		assert.Equal(t, 4, tasks[1].Start)
		assert.Equal(t, 8, tasks[1].End)

		// Worker 2: parts [8, 11) (3 parts) - small worker
		assert.Equal(t, 8, tasks[2].Start)
		assert.Equal(t, 11, tasks[2].End)
	})

	t.Run("single worker", func(t *testing.T) {
		// 7 parts, 1 worker -> all parts go to the single worker
		tasks, err := SplitWorkerTasks(7, 1)
		require.NoError(t, err)
		require.Len(t, tasks, 1)

		assert.Equal(t, 0, tasks[0].Start)
		assert.Equal(t, 7, tasks[0].End)
	})

	t.Run("zero tasks or workers", func(t *testing.T) {
		// 0 tasks, 3 workers -> should return error
		_, err := SplitWorkerTasks(0, 3)
		require.Error(t, err)
		assert.Contains(t, err.Error(), "numTasks must be greater than 0")

		_, err = SplitWorkerTasks(3, 0)
		require.Error(t, err)
		assert.Contains(t, err.Error(), "maxNumWorkers must be greater than 0")
	})

	t.Run("fewer tasks than workers", func(t *testing.T) {
		// 2 tasks, 5 workers -> only 2 workers, one for each
		tasks, err := SplitWorkerTasks(2, 5)
		require.NoError(t, err)
		require.Len(t, tasks, 2)

		// Worker 0: task 0
		assert.Equal(t, 0, tasks[0].Start)
		assert.Equal(t, 1, tasks[0].End)

		// Worker 1: task 1
		assert.Equal(t, 1, tasks[1].Start)
		assert.Equal(t, 2, tasks[1].End)
	})
}

func TestSplitHttpRanges(t *testing.T) {
	t.Run("even split", func(t *testing.T) {
		// 100 bytes, 25 byte parts -> 4 ranges
		ranges := SplitHttpRanges(100, 25)
		require.Len(t, ranges, 4)

		assert.Equal(t, int64(0), ranges[0].start)
		assert.Equal(t, int64(24), ranges[0].end)

		assert.Equal(t, int64(25), ranges[1].start)
		assert.Equal(t, int64(49), ranges[1].end)

		assert.Equal(t, int64(50), ranges[2].start)
		assert.Equal(t, int64(74), ranges[2].end)

		assert.Equal(t, int64(75), ranges[3].start)
		assert.Equal(t, int64(99), ranges[3].end)
	})

	t.Run("uneven split", func(t *testing.T) {
		// 105 bytes, 25 byte parts -> 5 ranges (last one is partial)
		ranges := SplitHttpRanges(105, 25)
		require.Len(t, ranges, 5)

		assert.Equal(t, int64(0), ranges[0].start)
		assert.Equal(t, int64(24), ranges[0].end)

		assert.Equal(t, int64(25), ranges[1].start)
		assert.Equal(t, int64(49), ranges[1].end)

		assert.Equal(t, int64(50), ranges[2].start)
		assert.Equal(t, int64(74), ranges[2].end)

		assert.Equal(t, int64(75), ranges[3].start)
		assert.Equal(t, int64(99), ranges[3].end)

		// Last range is partial (only 5 bytes)
		assert.Equal(t, int64(100), ranges[4].start)
		assert.Equal(t, int64(104), ranges[4].end)
	})

	t.Run("single range", func(t *testing.T) {
		// File size smaller than part size -> single range
		ranges := SplitHttpRanges(50, 100)
		require.Len(t, ranges, 1)

		assert.Equal(t, int64(0), ranges[0].start)
		assert.Equal(t, int64(49), ranges[0].end)
	})

	t.Run("exact single part", func(t *testing.T) {
		// File size exactly matches part size
		ranges := SplitHttpRanges(100, 100)
		require.Len(t, ranges, 1)

		assert.Equal(t, int64(0), ranges[0].start)
		assert.Equal(t, int64(99), ranges[0].end)
	})

	t.Run("small file", func(t *testing.T) {
		// Very small file
		ranges := SplitHttpRanges(1, 1024)
		require.Len(t, ranges, 1)

		assert.Equal(t, int64(0), ranges[0].start)
		assert.Equal(t, int64(0), ranges[0].end)
	})

	t.Run("large file with small parts", func(t *testing.T) {
		// Large file divided into many small parts
		ranges := SplitHttpRanges(1024, 100)
		require.Len(t, ranges, 11) // 10 full parts + 1 partial (24 bytes)

		// Check first range
		assert.Equal(t, int64(0), ranges[0].start)
		assert.Equal(t, int64(99), ranges[0].end)

		// Check last range (partial)
		assert.Equal(t, int64(1000), ranges[10].start)
		assert.Equal(t, int64(1023), ranges[10].end)
	})
}
